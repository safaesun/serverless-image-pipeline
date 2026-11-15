#!/bin/bash
API="https://xxxx.execute-api.eu-west-3.amazonaws.com"
RESP=$(curl -s -X POST "$API/upload" -H "Content-Type: application/json" -d '{"contentType":"image/jpeg"}')
echo $RESP
URL=$(echo $RESP | jq -r .uploadUrl)
ID=$(echo $RESP | jq -r .imageId)

curl -X PUT -H "Content-Type: image/jpeg" --upload-file photo.jpg "$URL"

sleep 15
aws dynamodb get-item --table-name images --key "{\"imageId\":{\"S\":\"$ID\"}}"
echo "ID=$ID"