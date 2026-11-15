# Serverless Image Processing Pipeline

Ce projet est un pipeline de traitement d'images entièrement serverless sur AWS. Quand une image est déposée dans S3, un message est envoyé dans SQS, puis Step Functions orchestre le traitement : validation, miniature, redimensionnement, watermark et extraction des métadonnées. CloudFront sert ensuite les images, DynamoDB garde le statut de chacune, et SNS m'envoie un email à la fin.

![Architecture](docs/architecture.png)

**Région** : eu-west-3 (Paris)

## Progression

### Étape 1 : Buckets S3
J'ai créé deux buckets : `img-source-safae` pour les images envoyées, et `img-dest-safae` pour les images traitées. L'accès public est bloqué sur les deux.

Chaque bucket a aussi une policy `DenyInsecureTransport`, qui refuse tout accès en HTTP non chiffré (`infra/s3-source-bucket-policy.json` et `infra/s3-dest-bucket-policy.json`).

### Étape 2 : DynamoDB
J'ai créé la table `images` (clé de partition `imageId`, mode à la demande). Pour chaque image, elle garde son statut (`PENDING_UPLOAD`, `PROCESSING`, `COMPLETED` ou `FAILED`), ses dimensions, et les chemins S3 de l'original, de la miniature et de la version finale.

### Étape 3 : SNS
J'ai créé la rubrique `image-notifications` et je m'y suis abonnée par email. À la fin du traitement de chaque image, je reçois un message qui m'indique si ça a réussi ou échoué.
### Étape 4 : SQS + DLQ
- `image-processing-queue` : délai de visibilité 180 s, DLQ après 3 réceptions.
- `image-processing-dlq` : reçoit les messages en échec.
- Access policy : autorise uniquement le bucket source à envoyer des messages (`infra/sqs-access-policy.json`).
### Étape 5 : Rôle IAM
Rôle `image-pipeline-lambda-role` partagé par les 3 Lambdas : logs CloudWatch + accès S3, DynamoDB, SNS, SQS et démarrage de Step Functions (`infra/iam-lambda-policy.json`). *Amélioration : un rôle par fonction (moindre privilège).*
### Étape 6 : Lambda Layer Pillow
Pillow est compilé pour Linux : le Layer `pillow-layer` est construit dans CloudShell (`scripts/build-layer.sh`) et partagé par `image-worker` sans l'embarquer dans le package de la fonction.
### Étape 7 : Lambda image-worker
Python 3.12, 1024 Mo, timeout 1 min, Layer Pillow. Une seule fonction avec un paramètre `action` : `validate`, `thumbnail`, `resize`, `watermark`, `metadata`, `finalize`, `failed` (`src/image_worker/lambda_function.py`). Les images qu'elle produit (miniature et version complète) seront enregistrées dans le bucket destination avec un en-tête `Cache-Control: immutable`, pour que CloudFront puisse les garder longtemps en cache.
### Étape 8 : Step Functions
Workflow Standard `image-pipeline` : **Validate** (retry sur erreurs Lambda) → **Parallel** (Thumbnail | Resize → Watermark | Metadata) → **Finalize**. Toute erreur passe par **MarkFailed** (statut FAILED + email) puis **Fail** (`infra/state-machine.asl.json`).

![Graphe Step Functions](docs/screenshots/01-stepfunctions-graph.png)
### Étape 9 : Lambda `start-workflow` et déclencheur SQS
J'ai créé `start-workflow` pour faire le lien entre la file SQS et Step Functions. Elle ne traite aucune image elle-même : son seul travail est de lancer le workflow.

Un déclencheur SQS (batch size 1) l'appelle pour chaque message de `image-processing-queue`. Son code (`src/start_workflow/lambda_function.py`) lit la notification S3 contenue dans le message, en extrait le nom du bucket et le chemin du fichier, puis démarre une exécution du workflow `image-pipeline`.

Si la fonction échoue, le message n'est pas perdu : il revient dans la file et est retenté. Après 3 tentatives, il part dans la DLQ. J'ai aussi réglé le timeout de la fonction (30 s) bien en dessous du délai de visibilité de la file (180 s), pour qu'un message en cours de traitement ne réapparaisse pas trop tôt.
### Étape 10 : Notification S3 vers SQS
J'ai configuré le bucket source pour qu'il prévienne le reste du pipeline dès qu'une image arrive. À chaque fichier ajouté dans le dossier `uploads/`, S3 dépose un message dans la file `image-processing-queue`.

J'ai limité la notification au préfixe `uploads/` pour que seuls les vrais uploads déclenchent un traitement, et pas n'importe quel autre fichier du bucket. Pour que S3 ait le droit d'écrire dans la file, la policy d'accès SQS de l'étape 4 autorise uniquement ce bucket à lui envoyer des messages.

C'est le début de l'architecture événementielle : l'upload ne lance pas le traitement directement. Il laisse un message dans SQS, qui sera lu ensuite par `start-workflow`.
### Étape 11 : Premier test de bout en bout
J'ai déposé une photo dans le dossier `uploads/` depuis la console S3, puis j'ai attendu pour voir si le pipeline réagissait tout seul. Je n'ai rien lancé à la main, et tout s'est déclenché dès l'upload.

Dans Step Functions, le workflow est allé jusqu'au bout et toutes les étapes sont passées au vert :

![Exécution réussie](docs/screenshots/02-stepfunctions-execution-success.png)

Côté DynamoDB, une ligne a été créée pour mon image. Elle est passée au statut `COMPLETED`, avec sa largeur et sa hauteur :

![Item DynamoDB](docs/screenshots/03-dynamodb-item-completed.png)

Dans le bucket destination, les deux versions sont bien là : la miniature dans `thumbnails/` et la grande image dans `full/` :

![Bucket destination](docs/screenshots/04-s3-destination-folders.png)

J'ai ouvert l'image de `full/` pour vérifier le watermark, et le texte apparaît bien en bas à droite :

![Image avec watermark](docs/screenshots/05-image-watermark.png)

Et pour finir, j'ai reçu l'email de SNS qui m'annonçait que le traitement était terminé :

![Email SNS](docs/screenshots/11-sns-email.png)
### Étape 12 : API pour envoyer les images
Jusqu'ici, je déposais les images à la main dans la console S3. Pour que n'importe quel client puisse en envoyer une, j'ai construit une petite API.

J'ai d'abord créé une Lambda, `presign` (`src/presign/lambda_function.py`). Quand elle reçoit une demande, elle fait quatre choses : elle vérifie que le type de fichier est accepté (JPEG, PNG ou WEBP), elle génère un identifiant unique pour l'image, elle crée une ligne dans DynamoDB avec le statut `PENDING_UPLOAD`, puis elle renvoie une URL pré-signée. Cette URL est une adresse S3 temporaire, valable 5 minutes, qui autorise l'envoi d'un seul fichier à un emplacement précis de `uploads/`. Elle lit le nom du bucket et de la table dans ses variables d'environnement (`SOURCE_BUCKET` et `TABLE_NAME`).

Ensuite, j'ai créé une API HTTP dans API Gateway, `image-upload-api`, avec une seule route, `POST /upload`, branchée sur cette Lambda. J'ai laissé le déploiement automatique activé sur l'étape `$default`, pour que chaque modification soit publiée sans action de ma part.

Le client n'envoie donc jamais son image à mon API : il demande d'abord une URL, puis il envoie son image directement à S3. Le bucket reste privé, personne n'a d'accès permanent, et les gros fichiers ne passent ni par Lambda ni par API Gateway. Le dépôt de l'image dans `uploads/` déclenche ensuite tout le pipeline des étapes précédentes.
### Étape 13 : Test de bout en bout via l'API
Cette fois, j'ai testé le pipeline comme le ferait un vrai client, depuis CloudShell, sans toucher à la console S3. J'ai demandé une URL d'upload à mon API (`POST /upload`), j'ai envoyé une photo directement à S3 avec cette URL, puis j'ai interrogé DynamoDB pour voir où en était le traitement (`scripts/test-upload.sh`).

L'API m'a renvoyé un identifiant d'image, S3 a accepté l'upload (code HTTP 200), et quelques secondes plus tard la ligne de DynamoDB est passée à `COMPLETED`, avec les dimensions de l'image et les chemins de la miniature et de la version complète :

![Test via l'API](docs/screenshots/06-api-presigned-test.png)
### Étape 14 : CloudFront
Distribution CloudFront devant le bucket destination, qui reste **privé** : accès uniquement via Origin Access Control (OAC) grâce à la bucket policy `AllowCloudFrontRead`. HTTPS obligatoire, cache `CachingOptimized`, compression. Les objets ont `Cache-Control: immutable` et des noms uniques : pas d'invalidation nécessaire.

![Cache Miss puis Hit](docs/screenshots/07-cloudfront-miss-hit.png)
### Étape 15 : Gestion du cycle de vie S3

Des règles Lifecycle ont été mises en place sur les deux buckets afin d'automatiser la gestion des fichiers et d'optimiser le stockage.

- **Bucket source (`uploads/`)** : les images originales passent en classe Standard-IA après 30 jours et sont supprimées après 365 jours. Les chargements multipart incomplets sont supprimés après 7 jours.


Cette configuration permet de réduire les coûts de stockage et d'éviter l'accumulation de fichiers inutilisés.

![Règles Lifecycle S3](docs/screenshots/10-s3-lifecycle-rules.png)