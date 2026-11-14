import io
import os
import boto3
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont, ImageOps

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
sns = boto3.client("sns")

DEST = os.environ["DEST_BUCKET"]
TOPIC = os.environ["TOPIC_ARN"]
WATERMARK = os.environ.get("WATERMARK_TEXT", "(c) MonProjet")
MAX_BYTES = 10 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
CACHE = "public, max-age=31536000, immutable"


def now():
    return datetime.now(timezone.utc).isoformat()


def update(image_id, **fields):
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in fields)
    ddb.update_item(Key={"imageId": image_id}, UpdateExpression=expr,
                    ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def read_bytes(bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def save_jpeg(img, key, quality=85):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    s3.put_object(Bucket=DEST, Key=key, Body=buf.getvalue(),
                  ContentType="image/jpeg", CacheControl=CACHE)


def base(e):
    return {"imageId": e["imageId"], "bucket": e["bucket"], "key": e["key"]}


def validate(e):
    head = s3.head_object(Bucket=e["bucket"], Key=e["key"])
    if head["ContentLength"] > MAX_BYTES:
        raise ValueError("Fichier trop gros (max 10 Mo)")
    img = Image.open(io.BytesIO(read_bytes(e["bucket"], e["key"])))
    fmt = img.format
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"Format non supporte: {fmt}")
    img.verify()
    update(e["imageId"], status="PROCESSING", originalKey=e["key"],
           sizeBytes=head["ContentLength"], validatedAt=now())
    return {**base(e), "format": fmt}


def thumbnail(e):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(read_bytes(e["bucket"], e["key"]))))
    img.thumbnail((300, 300))
    key = f"thumbnails/{e['imageId']}.jpg"
    save_jpeg(img, key, 80)
    return {**base(e), "thumbnailKey": key}


def resize_full(e):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(read_bytes(e["bucket"], e["key"]))))
    img.thumbnail((1920, 1920))
    key = f"full/{e['imageId']}.jpg"
    save_jpeg(img, key, 85)
    return {**base(e), "fullKey": key}


def watermark(e):
    key = f"full/{e['imageId']}.jpg"
    img = Image.open(io.BytesIO(read_bytes(DEST, key))).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    size = max(18, img.width // 25)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), WATERMARK, font=font)
    x = img.width - (box[2] - box[0]) - 20
    y = img.height - (box[3] - box[1]) - 20
    draw.text((x + 2, y + 2), WATERMARK, font=font, fill=(0, 0, 0, 120))
    draw.text((x, y), WATERMARK, font=font, fill=(255, 255, 255, 180))
    save_jpeg(Image.alpha_composite(img, overlay), key, 85)
    return {**base(e), "fullKey": key, "watermarked": True}


def extract_metadata(e):
    data = read_bytes(e["bucket"], e["key"])
    img = Image.open(io.BytesIO(data))
    meta = {"width": img.width, "height": img.height, "format": img.format,
            "mode": img.mode, "sizeBytes": len(data)}
    return {**base(e), "metadata": meta}


def finalize(e):
    merged = {}
    for r in e["results"]:
        merged.update(r)
    meta = merged.get("metadata", {})
    update(e["imageId"], status="COMPLETED",
           thumbnailKey=merged.get("thumbnailKey"), fullKey=merged.get("fullKey"),
           width=meta.get("width"), height=meta.get("height"),
           format=meta.get("format"), completedAt=now())
    msg = (f"Image {e['imageId']} traitee avec succes.\n"
           f"Thumbnail: {merged.get('thumbnailKey')}\nFull: {merged.get('fullKey')}")
    sns.publish(TopicArn=TOPIC, Subject="[Images] Traitement reussi", Message=msg)
    return {"imageId": e["imageId"], "status": "COMPLETED"}


def failed(e):
    err = e.get("error", {})
    cause = str(err.get("Cause", "inconnue"))[:500]
    update(e["imageId"], status="FAILED", errorMessage=cause, failedAt=now())
    sns.publish(TopicArn=TOPIC, Subject="[Images] Traitement ECHOUE",
                Message=f"Image {e['imageId']} en echec.\nErreur: {err.get('Error')}\nCause: {cause}")
    return {"imageId": e["imageId"], "status": "FAILED"}


ACTIONS = {"validate": validate, "thumbnail": thumbnail, "resize": resize_full,
           "watermark": watermark, "metadata": extract_metadata,
           "finalize": finalize, "failed": failed}


def lambda_handler(event, context):
    action = event["action"]
    payload = event["input"] if action in ("finalize", "failed") else event
    return ACTIONS[action](payload)