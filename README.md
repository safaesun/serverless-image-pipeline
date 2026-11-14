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