"""
Python Script to Extract FHIR Resource from Cerner FHIR APIs
"""
import base64
import logging
import sys
import time

import requests
from typing_extensions import NotRequired
from typing_extensions import Optional
from typing_extensions import TypedDict
from typing_extensions import Unpack

REGION = 'us-east-1'
ID_PARAM = "identifier"
ID_PREFIX = "urn:oid:2.16.840.1.113883.3.13.6"

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(log_format)
LOGGER.addHandler(handler)


class BasicTokenService:
    """
    Basic Client Credentials OAuth Service
    """
    _token: Optional[str]
    _token_type: Optional[str]
    _expires: int
    client_id: str
    client_secret: str
    token_url: str
    scope: str
    expiration_threshold: int
    timeout: int

    class _BasicTokenServiceKwargs(TypedDict):
        client_id: str
        client_secret: str
        token_url: str
        scope: str
        session: NotRequired[requests.Session]
        expiration_threshold: NotRequired[int]
        timeout: NotRequired[int]

    def __init__(self, **kwargs: Unpack[_BasicTokenServiceKwargs]) -> None:
        """
        Token Service Constructor
        :keyword client_id: Client ID
        :keyword client_secret: Client Secret
        :keyword token_url: URL to retrieve tokens
        :keyword expiration_threshold: Time before expiration to retrieve a new token
        :keyword timeout: Time to wait for a response for a token
        """
        self.client_id = kwargs['client_id']
        self.client_secret = kwargs['client_secret']
        self.token_url = kwargs['token_url']
        self.scope = kwargs['scope']
        self.expiration_threshold = kwargs.get('expiration_threshold', 30)
        self.timeout = kwargs.get('timeout', 30)
        self.session = kwargs.get('session', requests.Session())
        self._token = None
        self._token_type = None
        self._expires = 0
        self._get_token()

    @property
    def token(self) -> Optional[str]:
        """
        Get Token
        :return: Token
        """
        if self._token and int(time.time()) < (self._expires - self.expiration_threshold):
            return self._token
        return self._get_token()

    def _get_token(self) -> Optional[str]:
        try:
            credentials = base64.b64encode(f'{self.client_id}:{self.client_secret}'.encode())
            response = \
                self.session.post(self.token_url,
                                  headers={'Authorization': f'Basic {credentials.decode()}',
                                           'Content-Type': 'application/x-www-form-urlencoded'},
                                  data={'grant_type': 'client_credentials',
                                        'scope': self.scope})
            if 200 <= response.status_code < 300:
                payload: dict = response.json()
                self._token = payload.get('access_token')
                self._expires = int(time.time()) + int(payload.get('expires_in', 0))
                self._token_type = payload.get('token_type', '')
                return self._token
            LOGGER.error('FAILED TO RETRIEVE TOKEN: (%d) %s', response.status_code, response.text)
        except requests.RequestException as ex:
            LOGGER.error('FAILED TO RETRIEVE TOKEN: %s',
                         ex.response.text if ex.response is not None else str(ex))
        return None


class FhirRequestError(Exception):
    """
    Exception class for an unexpected response from the Fhir Service
    """
    _response: requests.Response

    def __init__(self, response: requests.Response):
        self._response = response
        super().__init__(response.text)

    @property
    def response(self) -> requests.Response:
        """
        HTTP Status Code Property
        """
        return self._response


class FhirTokenError(Exception):
    """
    FHIR Token Exception, for failed to retrieval token
    """


class FhirZeroResponseError(Exception):
    """
    FHIR Response Contains Zero Entry, expected only one
    """


class FhirNotUniqueResponseError(Exception):
    """
    FHIR Response Contains More than One Entries, expected only one
    """


class FhirRequestDataError(Exception):
    """
    Request data error
    """


class FhirService:
    """
    FHIR REST Service
    """
    token_service: BasicTokenService
    session: requests.Session
    base_url: str

    class _FhirServiceKwargs(TypedDict):
        client_id: str
        client_secret: str
        token_url: str
        base_url: str
        scope: str

    def __init__(self, **kwargs: Unpack[_FhirServiceKwargs]) -> None:
        """
        FhirService Constructor
        :keyword client_id: The OAuth Client ID
        :keyword client_secret: The OAuth Client Secret
        :keyword token_url: The OAuth Token URL
        :keyword base_url: The API Base URL for the service
        """
        self.token_service = BasicTokenService(client_id=kwargs['client_id'],
                                               client_secret=kwargs['client_secret'],
                                               token_url=kwargs['token_url'],
                                               scope=kwargs['scope'])
        self.base_url = kwargs['base_url']

        self.session = requests.Session()

    def get_fhir_resource(self, url: str) -> requests.Response:
        """
        Get all resources of the specified resource_type and patient

        :param url: url for next resources
        :return:
        """
        token = self.token_service.token
        if token:
            LOGGER.debug("Sending request: %s", url)
            response = self.session.get(url, headers={'Accept': 'application/json+fhir',
                                                      'Authorization':
                                                          f'Bearer {token}'},
                                        timeout=1200)
            if response.status_code == 200:
                return response

            raise FhirRequestError(response)

        raise FhirTokenError('Retrieve token Failed.')

    def search_fhir_resource_by_param(self, resource_type: str, param: str,
                                      value: str) -> requests.Response:
        """
        Get all resources of the specified resource_type and patient

        :param resource_type: FHIR Resource Type
        :param param: search parameter name
        :param value: search parameter value
        :return:
        """
        url = f'{self.base_url}/{resource_type}?{param}={value}'
        LOGGER.debug('search url %s', url)
        return self.get_fhir_resource(url)
