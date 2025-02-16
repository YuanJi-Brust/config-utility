"""
Python Script to Extract FHIR Resource from Cerner FHIR APIs
"""
import logging
import sys

from fhir_service import FhirService, FhirRequestDataError, FhirRequestError
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


def load_mrn_from_file(file: str) -> list[str]:
    """
    Loads the MEDIPAC MRNs from the file where they are stored
    :param file: The path to the file with the MRNs
    :return: A list of the MEDIPAC MRNs
    """

    with open(file, 'r', encoding='utf-8') as fh:
        contents = fh.read().splitlines()

    return [x for x in contents if x.replace('"', '').upper() != 'MRN']


def get_configuration() -> dict:
    """
    :return: Configuration as dictionary
    """
    tenant_id = 'a33bb2f7-1f6a-4097-bd5f-175f3ee1706d'
    host_url = 'hosts/fhir-ehr.cerner.com/protocols/oauth2/profiles/smart-v1/token'
    config = {
        "client_id": "6b9f5e6e-c18a-4d44-a250-e62720fb6c23",
        "client_secret": "MSdF9T3VpRBzyvwkXLIBuJDNLsTF5_Yu",
        "token_url": f"https://authorization.cerner.com/tenants/{tenant_id}/{host_url}",
        "api_url": f"https://fhir-ehr.cerner.com/r4/{tenant_id}",
        "output_bucket": "ahavi-bronze-poc",
        "resource_prefix": "H1_resources",
        "error_prefix": "errors"}
    return config


def parse_bundle(body: dict) -> tuple[list[dict], str]:
    """
    Retrieve all Resources of resource_type for patient id mrn_save resources as ndjson file to S3
    :param body: Response json object
    :return: tuple of list of resources and link for next page of resource
    """
    if body.get('resourceType', '') != 'Bundle':
        return [], ''

    next_link = ''
    for link in body['link']:
        if link.get('relation', '') == 'next':
            next_link = link['url']

    resources = []
    for entry in body.get('entry', []):
        resources.append(entry['resource'])

    return resources, next_link


def get_patient_id(param: str, value: str, fhir_service: FhirService) -> str:
    """
    Retrieve Patient ID, mrn_save patient id as roster file to S3
    :param param: search parameter name
    :param value: search parameter value
    :param fhir_service: FhirService instance
    :return: None
    """
    response = fhir_service.search_fhir_resource_by_param('Patient', param, value)
    resources, next_link = parse_bundle(response.json())

    if len(resources) != 1 or next_link:
        raise FhirRequestDataError(f"Zero or More than one patients found for mrn {value}")

    resource = resources[0]
    return resource.get('id')


def main(roster_file: str) -> None:
    """
    Retrieve FHIR Patients by MRN list, save patient ids to S3
    :return: None
    """

    config = get_configuration()

    LOGGER.info('Begin process roster file %s', roster_file)

    fhir_service = FhirService(client_id=config['client_id'], client_secret=config['client_secret'],
                               token_url=config['token_url'], base_url=config['api_url'],
                               scope='system/Patient.read')

    mrn_list = load_mrn_from_file(roster_file)
    patient_ids = []
    mrn_in_errors = []
    count = 0
    for mrn in mrn_list:
        count += 1
        LOGGER.info('Count:%s Process MRN: %s', count, mrn)
        try:
            value = ID_PREFIX + '|' + mrn
            patient_id = get_patient_id(ID_PARAM, value, fhir_service)
            patient_ids.append(patient_id)
        except FhirRequestError as ex:
            LOGGER.error('Failed to retrieve Patient for MRN %s: %s', mrn, ex.response.text)
            mrn_in_errors.append(mrn)
        except FhirRequestDataError as ex:
            LOGGER.error('Failed to retrieve Patient for MRN %s: %s', mrn, ex)
            mrn_in_errors.append(mrn)

    if patient_ids:
        file_name = roster_file.replace('.', '_patient_ids.')
        with open(file_name, 'w') as f:
            for patient_id in patient_ids:
                f.write(patient_id + '\n')

    if mrn_in_errors:
        file_name = roster_file.replace('.', '_error.')
        with open(file_name, 'w') as f:
            for mrn in mrn_in_errors:
                f.write(mrn + '\n')

    LOGGER.info('End process roster file %s', roster_file)


if __name__ == '__main__':
    main('MRN_5009_4.csv')
