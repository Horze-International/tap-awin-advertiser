import math
from datetime import timedelta
import pytz
import humps

import singer
from singer import metrics, metadata, Transformer, utils
from singer.utils import strptime_to_utc, strftime

from tap_awin_advertiser.streams import flatten_streams, STREAMS

LOGGER = singer.get_logger()
BASE_URL = 'https://api.awin.com'


def write_schema(catalog, stream_name):
    stream = catalog.get_stream(stream_name)
    schema = stream.schema.to_dict()
    try:
        singer.write_schema(stream_name, schema, stream.key_properties)
    except OSError as err:
        LOGGER.error('OS Error writing schema for: {}'.format(stream_name))
        raise err

def write_record(stream_name, record, time_extracted):
    try:
        singer.messages.write_record(stream_name, record, time_extracted=time_extracted)
    except OSError as err:
        LOGGER.error('OS Error writing record for: {}'.format(stream_name))
        LOGGER.error('Stream: {}, record: {}'.format(stream_name, record))
        raise err
    except TypeError as err:
        LOGGER.error('Type Error writing record for: {}'.format(stream_name))
        LOGGER.error('Stream: {}, record: {}'.format(stream_name, record))
        raise err

def get_bookmark(state, stream, default, bookmark_field=None, parent=None, parent_id=None):
    if (state is None) or ('bookmarks' not in state):
        return default

    if bookmark_field is None:
        return default

    if parent and parent_id:
        key = '{}(parent_{}:{})'.format(bookmark_field, parent, parent_id)
    else:
        key = bookmark_field

    return (
        state
        .get('bookmarks', {})
        .get(stream, {})
        .get(key, default)
    )

def write_bookmark(state, stream, value, bookmark_field=None, parent=None, parent_id=None):
    if parent and parent_id:
        key = '{}(parent_{}:{})'.format(bookmark_field, parent, parent_id)
    else:
        key = bookmark_field
    if 'bookmarks' not in state:
        state['bookmarks'] = {}
    if stream not in state['bookmarks']:
        state['bookmarks'][stream] = {}

    state['bookmarks'][stream][key] = value
    LOGGER.info('Write state for Stream: {}, {} ID: {}, value: {}'.format(
        stream, parent, parent_id, value))
    singer.write_state(state)

def process_records(catalog, #pylint: disable=too-many-branches
                    stream_name,
                    records,
                    time_extracted,
                    bookmark_field=None,
                    max_bookmark_value=None,
                    last_datetime=None):
    stream = catalog.get_stream(stream_name)
    schema = stream.schema.to_dict()
    stream_metadata = metadata.to_map(stream.metadata)

    with metrics.record_counter(stream_name) as counter:
        for record in records:
            # Transform record for Singer.io
            with Transformer() as transformer:
                transformed_record = transformer.transform(
                    record,
                    schema,
                    stream_metadata)

                # Reset max_bookmark_value to new value if higher
                if bookmark_field and (bookmark_field in transformed_record):
                    bookmark_date = transformed_record.get(bookmark_field)
                    bookmark_dttm = strptime_to_utc(bookmark_date)
                    last_dttm = strptime_to_utc(last_datetime)

                    if not max_bookmark_value:
                        max_bookmark_value = last_datetime

                    max_bookmark_dttm = strptime_to_utc(max_bookmark_value)

                    if bookmark_dttm > max_bookmark_dttm:
                        max_bookmark_value = strftime(bookmark_dttm)

                    # LOGGER.info('record1: {}'.format(record)) # TESTING, comment out
                    write_record(stream_name, transformed_record, \
                        time_extracted=time_extracted)
                    counter.increment()
                else:
                    # LOGGER.info('record2: {}'.format(record)) # TESTING, comment out
                    write_record(stream_name, transformed_record, time_extracted=time_extracted)
                    counter.increment()

        LOGGER.info('Stream: {}, Processed {} records'.format(stream_name, counter.value))
        return max_bookmark_value, counter.value

# Sync a specific parent or child endpoint.
def sync_endpoint(
        client,
        config,
        catalog,
        state,
        stream_name,
        endpoint_config,
        sync_streams,
        selected_streams,
        parent_id=None):

    # endpoint_config variables
    base_path = endpoint_config.get('path', stream_name)
    bookmark_field = next(iter(endpoint_config.get('replication_keys', [])), None)
    params = endpoint_config.get('params', {})
    bookmark_query_field_from = endpoint_config.get('bookmark_query_field_from')
    bookmark_query_field_to = endpoint_config.get('bookmark_query_field_to')
    data_key_array = endpoint_config.get('data_key_array')
    id_fields = endpoint_config.get('key_properties')
    parent = endpoint_config.get('parent')
    date_window_size = int(endpoint_config.get('date_window_size', '1'))

    # tap config variabless
    start_date = config.get('start_date')
    attribution_window = config.get('attribution_window', 30)

    last_datetime = get_bookmark(state, stream_name, start_date, bookmark_field, parent, parent_id)
    max_bookmark_value = last_datetime

    # Convert to datetimes in local/ad account timezone
    now_datetime = utils.now()
    last_dttm = strptime_to_utc(last_datetime)

    if bookmark_query_field_from and bookmark_query_field_to:
        # date_window_size: Number of days in each date window
        # Set start window
        start_window = now_datetime - timedelta(days=attribution_window)
        if last_dttm < start_window:
            start_window = last_dttm + timedelta(days=1) # makes sure that we don't have duplicated data
        # Set end window
        end_window = start_window + timedelta(days=date_window_size)
        if end_window > now_datetime:
            end_window = now_datetime

    else:
        start_window = last_dttm
        end_window = now_datetime
        diff_sec = (end_window - start_window).seconds
        date_window_size = math.ceil(diff_sec / (3600 * 24)) # round-up difference to days

    endpoint_total = 0
    total_records = 0

    while start_window < now_datetime:
        LOGGER.info('START Sync for Stream: {}{}'.format(
            stream_name,
            ', Date window from: {} to {}'.format(start_window.date(), end_window.date()) \
                if bookmark_query_field_from else ''))

        if bookmark_query_field_from and bookmark_query_field_to:
            # Query parameter startDate and endDate must be in Eastern time zone
            # API will error if future dates are requested

            # DAY based
            window_start_dt_str = start_window.date().strftime('%Y-%m-%dT00:00:00')
            window_end_dt_str = end_window.date().strftime('%Y-%m-%dT23:59:59')

            params[bookmark_query_field_from] = window_start_dt_str
            params[bookmark_query_field_to] = window_end_dt_str

        path = base_path.format(
            parent_id=parent_id)

        total_records = 0

        # concate params
        querystring = '&'.join(['%s=%s' % (key, value) for (key, value) in params.items()])

        # initialize url
        url = '{}/{}?{}'.format(
            client.base_url,
            path,
            querystring)

        # API request data
        data = {}
        try:
            data = client.get(
                url=url,
                endpoint=stream_name)
        except Exception as err:
            LOGGER.error('{}'.format(err))
            LOGGER.error('URL for Stream {}: {}'.format(stream_name, url))
            raise Exception(err)

        # time_extracted: datetime when the data was extracted from the API
        time_extracted = utils.now()
        if not data or data is None or data == {}:
            LOGGER.info('No data results returned')
        else:
            # Transform data with transform_json from transform.py
            # The data_key_array identifies the array/list of records below the <root> element
            # LOGGER.info('data = {}'.format(data)) # TESTING, comment out
            transformed_data = [] # initialize the record list

            if data_key_array:
                data_records = data.get(data_key_array, [])
            else:
                data_records = data

            for record in data_records:
                # Add parent id field/value
                if parent and parent_id and parent not in record:
                    record[parent] = parent_id

                # transform record (remove inconsistent use of CamelCase)
                try:
                    transformed_record = humps.decamelize(record)
                except Exception as err:
                    LOGGER.error('{}'.format(err))
                    LOGGER.error('error record: {}'.format(record))
                    raise Exception(err)

                transformed_data.append(transformed_record)
                # End for record in array
            # End non-stats stream

            # LOGGER.info('transformed_data = {}'.format(transformed_data)) # COMMENT OUT
            if not transformed_data or transformed_data is None:
                LOGGER.info('No transformed data for data = {}'.format(data))
            else:

                # Process records and get the max_bookmark_value and record_count
                if stream_name in sync_streams:
                    max_bookmark_value, record_count = process_records(
                        catalog=catalog,
                        stream_name=stream_name,
                        records=transformed_data,
                        time_extracted=time_extracted,
                        bookmark_field=bookmark_field,
                        max_bookmark_value=max_bookmark_value,
                        last_datetime=last_datetime)
                    LOGGER.info('Stream {}, batch processed {} records'.format(
                        stream_name, record_count))

                # Loop thru parent batch records for each children objects (if should stream)
                children = endpoint_config.get('children')
                if children:
                    for child_stream_name, child_endpoint_config in children.items():
                        if child_stream_name in sync_streams:
                            LOGGER.info('START Syncing: {}'.format(child_stream_name))
                            write_schema(catalog, child_stream_name)
                            # For each parent record
                            for record in transformed_data:
                                i = 0
                                # Set parent_id
                                for id_field in id_fields:
                                    if i == 0:
                                        parent_id_field = id_field
                                    if id_field == 'id':
                                        parent_id_field = id_field
                                    i = i + 1
                                parent_id = record.get(parent_id_field)

                                # sync_endpoint for child
                                LOGGER.info(
                                    'START Sync for Stream: {}, parent_stream: {}, parent_id: {}'\
                                        .format(child_stream_name, stream_name, parent_id))

                                child_total_records = sync_endpoint(
                                    client=client,
                                    config=config,
                                    catalog=catalog,
                                    state=state,
                                    stream_name=child_stream_name,
                                    endpoint_config=child_endpoint_config,
                                    sync_streams=sync_streams,
                                    selected_streams=selected_streams,
                                    parent_id=parent_id)

                                LOGGER.info(
                                    'FINISHED Sync for Stream: {}, parent_id: {}, total_records: {}'\
                                        .format(child_stream_name, parent_id, child_total_records))
                                # End transformed data record loop
                            # End if child in sync_streams
                        # End child streams for parent
                    # End if children

                # Parent record batch
                total_records = total_records + record_count
                endpoint_total = endpoint_total + record_count

                LOGGER.info('Synced Stream: {}, records: {}'.format(
                    stream_name,
                    total_records))

                # Update the state with the max_bookmark_value for the stream date window
                # Snapchat Ads API does not allow page/batch sorting; bookmark written for date window
                if bookmark_field and stream_name in selected_streams:
                    write_bookmark(state, stream_name, max_bookmark_value, bookmark_field, parent, parent_id)

        # Increment date window and sum endpoint_total
        start_window = end_window + timedelta(days=1)
        next_end_window = end_window + timedelta(days=date_window_size)
        if next_end_window > now_datetime:
            end_window = now_datetime
        else:
            end_window = next_end_window
        # End date window

    # Return total_records (for date windows)
    return endpoint_total


# Currently syncing sets the stream currently being delivered in the state.
# If the integration is interrupted, this state property is used to identify
#  the starting point to continue from.
# Reference: https://github.com/singer-io/singer-python/blob/master/singer/bookmarks.py#L41-L46
def update_currently_syncing(state, stream_name):
    if (stream_name is None) and ('currently_syncing' in state):
        del state['currently_syncing']
    else:
        singer.set_currently_syncing(state, stream_name)
    singer.write_state(state)


def sync(client, config, catalog, state):
    # Get selected_streams from catalog, based on state last_stream
    #   last_stream = Previous currently synced stream, if the load was interrupted
    last_stream = singer.get_currently_syncing(state)
    LOGGER.info('last/currently syncing stream: {}'.format(last_stream))
    selected_streams = []
    for stream in catalog.get_selected_streams(state):
        selected_streams.append(stream.stream)
    LOGGER.info('selected_streams: {}'.format(selected_streams))
    if not selected_streams or selected_streams == []:
        return

    # Get the streams to sync (based on dependencies)
    sync_streams = []
    flat_streams = flatten_streams()
    # Loop thru all streams
    for stream_name, stream_metadata in flat_streams.items():
        # If stream has a parent_stream, then it is a child stream
        parent_stream = stream_metadata.get('parent_stream')

        if stream_name in selected_streams:
            LOGGER.info('stream: {}, parent: {}'.format(
                stream_name, parent_stream))
            if stream_name not in sync_streams:
                sync_streams.append(stream_name)
            if parent_stream and parent_stream not in sync_streams:
                sync_streams.append(parent_stream)
    LOGGER.info('Sync Streams: {}'.format(sync_streams))

    # Loop through selected_streams
    # Loop through endpoints in selected_streams
    for stream_name, endpoint_config in STREAMS.items():
        if stream_name in sync_streams:
            LOGGER.info('START Syncing: {}'.format(stream_name))
            write_schema(catalog, stream_name)
            update_currently_syncing(state, stream_name)

            total_records = sync_endpoint(
                client=client,
                config=config,
                catalog=catalog,
                state=state,
                stream_name=stream_name,
                endpoint_config=endpoint_config,
                sync_streams=sync_streams,
                selected_streams=selected_streams)

            update_currently_syncing(state, None)
            LOGGER.info('FINISHED Syncing: {}, total_records: {}'.format(
                stream_name,
                total_records))
