# Serverless Image Processing Pipeline

Pipeline serverless AWS : un upload dans S3 déclenche SQS, puis Step Functions orchestre le traitement (validation, miniature, redimensionnement, watermark, métadonnées). CloudFront sert les images. DynamoDB stocke le statut, SNS notifie.

![Architecture](docs/architecture.png)

**Région** : eu-west-3 (Paris)

## Progression