# Serverless Image Processing Pipeline

Pipeline serverless AWS : un upload dans S3 déclenche SQS, puis Step Functions orchestre le traitement (validation, miniature, redimensionnement, watermark, métadonnées). CloudFront sert les images. DynamoDB stocke le statut, SNS notifie.

![Architecture](docs/architecture.png)

**Région** : eu-west-3 (Paris)

## Progression
### Étape 1 : Buckets S3
- `SOURCE_BUCKET` (uploads) et `DEST_BUCKET` (images traitées), accès public bloqué.
- Bucket policy `DenyInsecureTransport` : tout accès HTTP non chiffré est refusé (`infra/s3-*-bucket-policy.json`).
### Étape 2 : DynamoDB
Table `images` (clé de partition `imageId`, mode on-demand). Elle stocke le statut (`PENDING_UPLOAD`, `PROCESSING`, `COMPLETED`, `FAILED`), les dimensions et les clés des fichiers.
### Étape 3 : SNS
Topic `image-notifications` avec abonnement email : envoie un email à la fin du traitement de chaque image (réussi ou échoué).
### Étape 4 : SQS + DLQ
- `image-processing-queue` : délai de visibilité 180 s, DLQ après 3 réceptions.
- `image-processing-dlq` : reçoit les messages en échec.
- Access policy : autorise uniquement le bucket source à envoyer des messages (`infra/sqs-access-policy.json`).
### Étape 5 : Rôle IAM
Rôle `image-pipeline-lambda-role` partagé par les 3 Lambdas : logs CloudWatch + accès S3, DynamoDB, SNS, SQS et démarrage de Step Functions (`infra/iam-lambda-policy.json`). *Amélioration : un rôle par fonction (moindre privilège).*