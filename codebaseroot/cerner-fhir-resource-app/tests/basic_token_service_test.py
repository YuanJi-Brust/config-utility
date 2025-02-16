"""
Tests for the FHIR Service and Token Service
"""
import time

import requests
import responses
from assertpy import assert_that

from patient_search_app import BasicTokenService


@responses.activate
def test_basic_token_service():
    """
    Basic token service test. Retrieve a single token.
    """
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=200,
                  json={'access_token': 'ImAValidOauthToken',
                        'expires_in': 3600, 'token_type': 'Bearer'})

    token_service = BasicTokenService(client_id='my_client_id',
                                      client_secret='my_client_secret',
                                      token_url='https://authorization.mockcerner.com/token',
                                      scope='system/TestScope.read')

    assert_that(token_service.token).is_equal_to('ImAValidOauthToken')
    assert_that(token_service._expires).is_greater_than(time.time())


@responses.activate
def test_basic_token_service_expired():
    """
    Tests that the service will only return an unexpired token.
    """
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=200,
                  json={'access_token': 'ImAnExpiredOauthToken',
                        'expires_in': -3600, 'token_type': 'Bearer'})
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=200,
                  json={'access_token': 'ImAValidOauthToken',
                        'expires_in': 3600, 'token_type': 'Bearer'})

    token_service = BasicTokenService(client_id='my_client_id',
                                      client_secret='my_client_secret',
                                      token_url='https://authorization.mockcerner.com/token',
                                      scope='system/TestScope.read')

    assert_that(token_service.token).is_equal_to('ImAValidOauthToken')
    assert_that(token_service._expires).is_greater_than(time.time())


@responses.activate
def test_basic_token_service_expired():
    """
    Tests that multiple calls to the service will return the same unexpired token.
    """
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=200,
                  json={'access_token': 'ImACachedOauthToken',
                        'expires_in': 3600, 'token_type': 'Bearer'})
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=200,
                  json={'access_token': 'ImTheNextOauthToken',
                        'expires_in': 3600, 'token_type': 'Bearer'})

    token_service = BasicTokenService(client_id='my_client_id',
                                      client_secret='my_client_secret',
                                      token_url='https://authorization.mockcerner.com/token',
                                      scope='system/TestScope.read')

    assert_that(token_service.token).is_equal_to('ImACachedOauthToken')
    assert_that(token_service.token).is_equal_to('ImACachedOauthToken')
    time.sleep(1)
    assert_that(token_service.token).is_equal_to('ImACachedOauthToken')


@responses.activate
def test_basic_token_service_expires_refresh():
    """
    Tests that the service will refresh if the token expires after the initial query.
    """
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=200,
                  json={'access_token': 'ImAboutToExpire',
                        'expires_in': 2, 'token_type': 'Bearer'})
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=200,
                  json={'access_token': 'ImAValidOauthToken',
                        'expires_in': 3600, 'token_type': 'Bearer'})

    token_service = BasicTokenService(client_id='my_client_id',
                                      client_secret='my_client_secret',
                                      token_url='https://authorization.mockcerner.com/token',
                                      scope='system/TestScope.read',
                                      expiration_threshold=1)

    assert_that(token_service.token).is_equal_to('ImAboutToExpire')
    assert_that(token_service.token).is_equal_to('ImAboutToExpire')

    time.sleep(2)

    assert_that(token_service.token).is_equal_to('ImAValidOauthToken')


@responses.activate
def test_basic_token_service_expires_failure_exception(caplog):
    """
    Tests that a failure to retrieve a token will return None and log an error message for a
    500-type Server Error.
    """
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=500,
                  body=requests.RequestException())

    token_service = BasicTokenService(client_id='my_client_id',
                                      client_secret='my_client_secret',
                                      token_url='https://authorization.mockcerner.com/token',
                                      scope='system/TestScope.read',
                                      expiration_threshold=1)

    assert_that(token_service.token).is_none()
    assert_that(caplog.text).contains('FAILED TO RETRIEVE TOKEN')


@responses.activate
def test_basic_token_service_expires_failure_error(caplog):
    """
    Tests that a failure to retrieve a token will return None and log an error message for a
    400-type Error.
    """
    responses.add(responses.POST, 'https://authorization.mockcerner.com/token', status=403,
                  body='Unauthorized')

    token_service = BasicTokenService(client_id='my_client_id',
                                      client_secret='my_client_secret',
                                      token_url='https://authorization.mockcerner.com/token',
                                      scope='system/TestScope.read',
                                      expiration_threshold=1)

    assert_that(token_service.token).is_none()
    assert_that(caplog.text).contains('FAILED TO RETRIEVE TOKEN')
