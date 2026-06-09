from aws_lambda_powertools.event_handler.api_gateway import Response
import json


def response_handler(content_type="application/json", headers={}, message="", code=200, data={}, error_message="", extra={}):
    data = {"message": message, "code": code, "data": data, "error_message": error_message, "extra": extra}
    # return {"statusCode": code,"headers": {"Content-Type": "application/json"},"body": data,"isBase64Encoded": False}
    _headers={
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'OPTIONS,POST,GET,PUT,DELETE,PATCH'
        }
    headers = {**_headers, **headers}
    
    return Response(status_code=code, content_type=content_type, body=data, headers=headers)