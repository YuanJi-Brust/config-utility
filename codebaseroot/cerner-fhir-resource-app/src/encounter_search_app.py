"""
Python Script to Extract FHIR Resource (Encounter) from Cerner FHIR APIs
"""
import logging
import sys

import pandas as pd
from pandas import DataFrame

from fhir_service import (FhirService, FhirRequestDataError, FhirRequestError,
                          FhirNotUniqueResponseError)

REGION = 'us-east-1'
PARAM_NAME = "identifier"
ROOT_PREFIX = "urn:oid:"

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(log_format)
LOGGER.addHandler(handler)


def convert_to_dataframe(file: str) -> DataFrame:
    """
    Convert csv file to dataframe

    :param file: The path to the file contains import data
    :return: DataFrame instance
    """
    df: DataFrame = pd.read_csv(file, sep=",", dtype=str)
    df['fhir_patient_id'] = ''
    df['fhir_encounter_id'] = ''
    df.fillna('', inplace=True)
    return df


def write_to_file(df: DataFrame, file: str):
    file_name = file.replace('.csv', '_output.csv')
    df.to_csv(file_name, index=False)


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


def get_id_pair_from_fhir(param: str, value: str, fhir_service: FhirService) -> tuple[str, str]:
    """
    Retrieve FHIR Patient ID, and Encounter ID for each search param/value provided

    :param param: search parameter name
    :param value: search parameter value
    :param fhir_service: FhirService instance
    :return: tuple of Patient ID and Encounter ID
    """
    response = fhir_service.search_fhir_resource_by_param('Encounter', param, value)
    resources, next_link = parse_bundle(response.json())

    if len(resources) == 0:
        return '', ''

    if len(resources) > 1 or next_link:
        raise FhirNotUniqueResponseError(f"More than one encounters found for root|id {value}")

    resource = resources[0]
    encounter_id = resource.get('id')
    subject = resource.get('subject')
    if encounter_id and subject and subject['reference']:
        reference: str = subject.get('reference')
        patient_id = reference.replace('Patient/', '')
        return patient_id, encounter_id
    else:
        raise FhirRequestDataError('Patient is not found for encounter id %s', encounter_id)


def main(roster_file: str) -> None:
    """
    Retrieve FHIR Patients by mrn list, extract patient id from Patient ans mrn_save patient ids to S3
    :return: None
    """

    config = get_configuration()

    LOGGER.info('Begin process roster file %s', roster_file)

    fhir_service = FhirService(client_id=config['client_id'], client_secret=config['client_secret'],
                               token_url=config['token_url'], base_url=config['api_url'],
                               scope='system/Encounter.read system/Patient.read')

    df = convert_to_dataframe(roster_file)
    output_ids: list[tuple] = []
    rows_fhir_encounter_not_found: list[tuple] = []
    rows_in_error_fhir: list[tuple] = []
    rows_in_error_data: list[tuple] = []
    rows_no_encounter_root_id: list[tuple] = []
    for index, row in df.iterrows():
        file_name = row['file_name']
        system = row['system']
        mrn = row['mrn']
        encounter_root = row['encounter_root']
        encounter_id = row['encounter_id']
        LOGGER.info('Count:%s Process Encounter ID: %s', index+1, encounter_id)

        if not encounter_root or not encounter_id:
            rows_no_encounter_root_id.append((file_name, system, mrn, encounter_root, encounter_id))
            continue

        try:
            value = ROOT_PREFIX + encounter_root + '|' + encounter_id
            id_pair: tuple[str, str] = get_id_pair_from_fhir(PARAM_NAME, value, fhir_service)
            fhir_patient_id = id_pair[0]
            fhir_encounter_id = id_pair[1]
            df.at[index, 'fhir_patient_id'] = fhir_patient_id
            df.at[index, 'fhir_encounter_id'] = fhir_encounter_id
            if fhir_patient_id and fhir_encounter_id:
                output_ids.append(id_pair)
            else:
                value = ROOT_PREFIX + system + '|' + mrn
                response = fhir_service.search_fhir_resource_by_param('Patient', PARAM_NAME, value)
                resources, next_link = parse_bundle(response.json())

                if len(resources) > 1 or next_link:
                    raise FhirRequestDataError(f"More than one Patients found for mrn {value}")

                if len(resources) == 1 or next_link:
                    resource = resources[0]
                    fhir_patient_id = resource.get('id', '')
                    df.at[index, 'fhir_patient_id'] = fhir_patient_id

                rows_fhir_encounter_not_found.append(
                    (file_name, system, mrn, encounter_root, encounter_id, fhir_patient_id,
                        fhir_encounter_id))

        except FhirRequestError as ex:
            LOGGER.error('Fhir Request Error for Encounter ROOT|ID: %s|%s: %s',
                         encounter_root, encounter_id, ex.response.text)
            status = str(ex.response.status_code)
            rows_in_error_fhir.append((file_name, system, mrn, encounter_root, encounter_id, status))
        except (FhirRequestDataError, FhirNotUniqueResponseError) as ex:
            LOGGER.error('Failed to retrieve Encounter for Encounter ROOT|ID: %s|%s: %s',
                         encounter_root, encounter_id, str(ex))
            rows_in_error_data.append((file_name, system, mrn, encounter_root, encounter_id, str(ex)))

    write_to_file(df, roster_file)

    m = ','
    nl = '\n'
    if output_ids:
        output_file = roster_file.replace('.', '_ids.')
        with open(output_file, 'w') as f:
            f.write("patient_id,encounter_id" + nl)
            for patient_id, encounter_id in output_ids:
                f.write(patient_id + m + encounter_id + nl)

    if rows_in_error_fhir:
        output_file = roster_file.replace('.', '_fhir_errors.')
        with open(output_file, 'w') as f:
            f.write("file_name,system,mrn,encounter_root,encounter_id,error_msg" + nl)
            for row in rows_in_error_fhir:
                row_string = ','.join(row) + nl
                f.write(row_string)

    if rows_in_error_data:
        output_file = roster_file.replace('.', '_data_errors.')
        with open(output_file, 'w') as f:
            f.write("file_name,system,mrn,encounter_root,encounter_id,error_msg" + nl)
            for row in rows_in_error_data:
                row_string = ','.join(row) + nl
                f.write(row_string)

    if rows_no_encounter_root_id:
        output_file = roster_file.replace('.', '_no_encounter_root_id.')
        with open(output_file, 'w') as f:
            f.write("file_name,system,mrn,encounter_root,encounter_id" + nl)
            for row in rows_no_encounter_root_id:
                row_string = ','.join(row) + nl
                f.write(row_string)

    if rows_fhir_encounter_not_found:
        output_file = roster_file.replace('.', '_encounter_no_found.')
        with open(output_file, 'w') as f:
            header = "file_name,system,mrn,encounter_root,encounter_id,fhir_patient_id,fhir_encounter_id"
            f.write(header + nl)
            for row in rows_fhir_encounter_not_found:
                row_string = ','.join(row) + nl
                f.write(row_string)

    LOGGER.info('End process roster file %s', roster_file)


if __name__ == '__main__':
    main('Replay_28_504.csv')
