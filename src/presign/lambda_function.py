import json
import os
import time
import uuid
import boto3
from botocore.config import Config

REGION = os.environ["AWS_REGION"]
BUCKET = os.environ["SOURCE_BUCKET"]
s3 = boto3.client("s3", region_name=REGION,
                  endpoint_url=f"https://s3.{REGION}.amazonaws.com",
                  config=Config(signature_version="s3v4"))
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
ALLOWED = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def resp(code, body):
    return {"statusCode": code,
            "headers": {"Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*"},
            "body": json.dumps(body)}


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return resp(400, {"error": "JSON invalide"})

    content_type = body.get("contentType", "image/jpeg")
    if content_type not in ALLOWED:
        return resp(400, {"error": "Type non autorise", "allowed": list(ALLOWED)})

    image_id = str(uuid.uuid4())
    key = f"uploads/{image_id}.{ALLOWED[content_type]}"
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=300)
    table.put_item(Item={"imageId": image_id, "status": "PENDING_UPLOAD",
                         "originalKey": key, "uploadRequestedAt": int(time.time())})
    return resp(200, {"imageId": image_id, "uploadUrl": url,
                      "contentType": content_type, "expiresIn": 300})