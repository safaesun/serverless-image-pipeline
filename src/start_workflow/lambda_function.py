import json
import os
import re
import urllib.parse
import boto3

sfn = boto3.client("stepfunctions")
STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]


def lambda_handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        # S3 envoie un message "s3:TestEvent" a la creation de la notification
        if "Records" not in body:
            print("Message ignore (pas un evenement S3):", body)
            continue
        for rec in body["Records"]:
            bucket = rec["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
            name = os.path.splitext(os.path.basename(key))[0]
            image_id = re.sub(r"[^A-Za-z0-9_-]", "_", name)
            sfn.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                input=json.dumps({"imageId": image_id, "bucket": bucket, "key": key}),
            )
            print(f"Workflow demarre pour {key}")
    return {"ok": True}