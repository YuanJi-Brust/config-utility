"""
Pytest Fixtures
"""
import json
from dataclasses import dataclass
from typing import Union

import pytest
from boto3 import Session
from moto import mock_aws
from typing_extensions import NotRequired, TypedDict, Unpack

import lambda_function

CONFIG = {
    'client_id': 'secret_client_id',
    'client_secret': 'secret_client_secret',
    'token_url': 'https://authorization.mockcerner.com/tenants/'
                 'b748fd97-7e18-4e5e-80bc-257c0270573f/hosts/'
                 'fhir-ehr.mockcerner.com/protocols/oauth2/profiles/smart-v1/token',
    'api_url': 'https://fhir-ehr.mockcerner.com/r4/'
               'b748fd97-7e18-4e5e-80bc-257c0270573f',
    'output_bucket': 'my_test_bucket',
    'resource_prefix': 'H1_resource',
    'error_prefix': 'errors'
}
SSM_PARAMETER_NAME = 'cerner-fhir-resource-configuration'

COVERAGE_JSON_FILE = './tests/bundle_coverage_123456.json'
PATIENT_JSON_FILE = './tests/patient_123456.json'


def load_json_file(path: str) -> dict:
    """
    Load a Json file.
    :param path: Path to the json file.
    :return: Dictionary containing FHIR Response json.
    """

    with open(path, 'r', encoding='utf-8') as input_file:
        return json.load(input_file)


@pytest.fixture
def mock_token(monkeypatch) -> None:
    """
    Pytest Fixture providing a mocked Token Service
    """
    monkeypatch.setattr(lambda_function.BasicTokenService, '_get_token',
                        lambda x: 'ImAValidOauthToken')


@pytest.fixture
def lambda_context():
    @dataclass
    class LambdaContext:
        function_name: str = "test"
        memory_limit_in_mb: int = 128
        invoked_function_arn: str = "arn:aws:lambda:eu-west-1:809313241:function:test"
        aws_request_id: str = "52fdfc07-2182-154f-163f-5f0f9a621d72"

    return LambdaContext()


@pytest.fixture
def boto_session() -> Session:
    """
    Creates the Boto Session Stack fixture
    """
    with mock_aws():
        yield Session(region_name='us-east-1')


@pytest.fixture
def s3_bucket(boto_session) -> callable:
    """
    Creates the S3 Bucket Factory Fixture
    """

    def bucket_factory(name: str) -> None:
        """
        Creates S3 Buckets in the Mock AWS Session
        :param name: Bucket Name
        """
        s3_client = boto_session.client('s3')
        s3_client.create_bucket(Bucket=name)

    return bucket_factory


@pytest.fixture
def s3_get_object(boto_session) -> callable:
    """
    Creates the S3 Object Retrieval Fixture
    """

    class _S3GetObjectKwargs(TypedDict):
        bucket: NotRequired[str]
        key: NotRequired[str]

    def _s3_get_object(url: str = '',
                       **kwargs: Unpack[_S3GetObjectKwargs]) -> str:
        """
        Calls S3 Get Object in the Mock AWS Session
        :keyword bucket: S3 Bucket (used when specifying key)
        :keyword key: S3 Key to Retrieve
        :keyword url: S3 URL
        :return: S3 Response
        """

        if 'bucket' not in kwargs and 'key' not in kwargs:
            bucket, key = url.split('/', maxsplit=1)
            if bucket.startswith('s3://'):
                bucket = bucket[5:]
        else:
            bucket = kwargs['bucket']
            key = kwargs['key']

        s3 = boto_session.client('s3')
        result = s3.get_object(Bucket=bucket,
                               Key=key)

        return result.get('Body', b'').read().decode('utf-8')

    return _s3_get_object


@pytest.fixture
def s3_list_objects(boto_session):
    """
    Creates the S3 Object Retrieval Fixture
    """

    class _S3ListObjectKwargs(TypedDict):
        bucket: NotRequired[str]
        prefix: NotRequired[str]

    def _s3_list_objects(url: str = '',
                         **kwargs: Unpack[_S3ListObjectKwargs]) -> list[str]:
        """
        Calls S3 Lists Object in the Mock AWS Session
        :keyword bucket: S3 Bucket (used when specifying key)
        :keyword prefix: S3 Key to list
        :keyword url: S3 URL to list
        :return: S3 Response
        """

        if 'bucket' not in kwargs and 'prefix' not in kwargs:
            bucket, prefix = url.split('/', maxsplit=1)
            if bucket.startswith('s3://'):
                bucket = bucket[5:]
        else:
            bucket = kwargs['bucket']
            prefix = kwargs['prefix']

        s3_client = boto_session.client('s3')
        result = s3_client.list_objects_v2(Bucket=bucket,
                                           Prefix=prefix)
        return [x.get('Key', '') for x in result.get('Contents', [])]

    return _s3_list_objects


@pytest.fixture
def s3_put_object(boto_session) -> callable:
    """
    Creates the S3 Object Upload Fixture
    """

    def _s3_put_object(bucket: str, key: str, contents: bytes) -> str:
        """
        Calls S3 Lists Object in the Mock AWS Session
        :param bucket: S3 Bucket (used when specifying key)
        :param key: S3 Key to list
        :param contents: Object contents to upload
        :return: S3 Response
        """
        s3 = boto_session.client('s3')
        return s3.put_object(Bucket=bucket,
                             Key=key,
                             Body=contents)

    return _s3_put_object


@pytest.fixture
def ssm_parameter(boto_session) -> callable:
    """
    Fixture to create the SSM Parameter and assign its value
    :return: SSM Put Parameter Response
    """

    def parameter_factory(name: str, value: Union[dict, str]) -> dict:
        """
        Calls SSM Put Parameter in the Mock AWS Session
        :param name: The Parameter Name to create
        :param value: The value to store in the parameter (As JSON if a dict)
        :return: SSM Response
        """
        ssm_client = boto_session.client('ssm')
        return ssm_client.put_parameter(Name=name, Type='String',
                                        Value=json.dumps(value)
                                        if type(value) is dict else value)

    return parameter_factory


@pytest.fixture
def sqs_event() -> callable:
    """
    SQS Response Factory for a given Patient ID, Resource Type, and Optional Parameter Name
    """

    def _event_factory(patient_id: str, resource: str, param: str) -> dict:
        event_body = {
            'patient_id': patient_id,
            'resource_type': resource,
            'date_param': param
        }
        return {"messageId": "059f36b4-87a3-44ab-83d2-661975830a7d",
                "receiptHandle": "AQEBwJnKyrHigUMZj6rYigCgxlaS3SLy0a...",
                "body": json.dumps(event_body),
                "attributes": {"ApproximateReceiveCount": "1",
                               "SentTimestamp": "1545082649183",
                               "SenderId": "AIDAIENQZJOLO23YVJ4VO",
                               "ApproximateFirstReceiveTimestamp": "1545082649185"},
                "messageAttributes": {},
                "md5OfBody": "e4e68fb7bd0e697a0ae8f1bb342846b3",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:test-queue",
                "awsRegion": "us-east-1"}

    return _event_factory
