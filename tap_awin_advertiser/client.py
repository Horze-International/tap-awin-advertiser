import time
import backoff
import requests
from requests.exceptions import ConnectionError

import singer
from singer import metrics

API_URL = 'https://api.awin.com'
LOGGER = singer.get_logger()


class Server5xxError(Exception):
    pass


class Server429Error(Exception):
    pass


class AwinError(Exception):
    pass


class AwinNotFoundError(AwinError):
    pass


ERROR_CODE_EXCEPTION_MAPPING = {
    404: AwinNotFoundError}


def get_exception_for_error_code(status_code):
    return ERROR_CODE_EXCEPTION_MAPPING.get(status_code, AwinError)

# Error message example
# {
#    "error": "exception",
#    "description": "Not Found (404 NOT_FOUND)"
# }
def raise_for_error(response):
    try:
        response.raise_for_status()
    except (requests.HTTPError, requests.ConnectionError) as error:
        try:
            content_length = len(response.content)
            if content_length == 0:
                # There is nothing we can do here since Snapchat has neither sent
                # us a 2xx response nor a response content.
                return
            #if status_code in [404]:
            #        LOGGER.error(response)

            response_json = response.json()
            status_code = response.status_code
            error_type = response_json.get('error')
            error_description = response_json.get('description')

            if error_type:
                error_message = '{} {}: {}'.format(status_code, error_type, error_description)
                LOGGER.error(error_message)
                ex = get_exception_for_error_code(status_code)
                raise ex(error_message)
            else:
                raise AwinError(error)
        except (ValueError, TypeError):
            raise AwinError(error)

class AwinClient:
    def __init__(self,
                 oauth2_token,
                 user_agent=None):
        self.__oauth2_token = oauth2_token
        self.__user_agent = user_agent
        self.__session = requests.Session()
        self.base_url = API_URL

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.__session.close()

    @backoff.on_exception(backoff.expo,
                          (Server5xxError, ConnectionError, Server429Error),
                          max_tries=7,
                          factor=3)
    def request(self, method, path=None, url=None, **kwargs):

        if not url and path:
            url = '{}/{}'.format(self.base_url, path)

        # endpoint = stream_name (from sync.py API call)
        if 'endpoint' in kwargs:
            endpoint = kwargs['endpoint']
            del kwargs['endpoint']
        else:
            endpoint = None

        if 'headers' not in kwargs:
            kwargs['headers'] = {}
        kwargs['headers']['Authorization'] = 'Bearer {}'.format(self.__oauth2_token)

        if self.__user_agent:
            kwargs['headers']['User-Agent'] = self.__user_agent

        with metrics.http_request_timer(endpoint) as timer:
            response = self.__session.request(method, url, **kwargs)
            timer.tags[metrics.Tag.http_status_code] = response.status_code

        if response.status_code >= 500:
            raise Server5xxError()

        if response.status_code == 429:
            try:
                response_json = response.json()
                error_type = response_json.get('error')
                error_description = response_json.get('description')

                if error_type == 'request.limit.exceeded':
                    # the request limit is set for one minute, sample error message:
                    #   Requests limit '20' times per '1' minutes' is exceeded
                    # so we just wait 1 minute and try again
                    LOGGER.warning('Request limit exceeded: {}'.format(error_description))
                    time.sleep(60)
            except Exception as err:
                pass

            raise Server429Error()

        if response.status_code != 200:
            LOGGER.error('{}: {}'.format(response.status_code, response.text))
            raise_for_error(response)

        # Catch invalid json response
        try:
            response_json = response.json()
        except Exception as err:
            LOGGER.error('{}'.format(err))
            LOGGER.error('response.headers = {}'.format(response.headers))
            LOGGER.error('response.reason = {}'.format(response.reason))
            raise Exception(err)

        return response_json

    def get(self, url, **kwargs):
        return self.request('GET', url=url, *kwargs)
