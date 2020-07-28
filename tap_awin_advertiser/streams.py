# streams: API URL endpoints to be called
# properties:
#   <root node>: Plural stream name for the endpoint
#   path: API endpoint relative path, when added to the base URL, creates the full path
#   key_properties: Primary key fields for identifying an endpoint record.
#   replication_method: INCREMENTAL or FULL_TABLE
#   replication_keys: bookmark_field(s), typically a date-time, used for filtering the results
#        and setting the state
#   data_key: JSON element containing the records for the endpoint
#   api_method: GET or POST; default = 'GET'
#   params: Query, sort, and other endpoint specific parameters; default = {}

STREAMS = {
    # Reference: https://wiki.awin.com/index.php/API_get_accounts
    'accounts': {
        'key_properties': ['account_id'],
        'replication_method': 'FULL_TABLE',
        'path': 'accounts',
        'data_key_array': 'accounts',
        'data_key_record': None,
        'params': {
            'type': 'advertiser'
        },
        'children': {
            # Reference: https://wiki.awin.com/index.php/API_get_publishers
            'publishers': {
                'key_properties': ['id'],
                'replication_method': 'FULL_TABLE',
                'path': 'advertisers/{parent_id}/publishers',
                'params': {}
            },
            # Reference: https://wiki.awin.com/index.php/API_get_transactions_list
            'transactions': {
                'key_properties': ['id'],
                'replication_method': 'INCREMENTAL',
                'replication_keys': ['transaction_date'],
                'bookmark_query_field_from': 'startDate',
                'bookmark_query_field_to': 'endDate',
                'path': 'advertisers/{parent_id}/transactions/',
                'date_window_size': 30,
                'params': {
                    'timezone': 'UTC',
                    'dateType': 'transaction',
                    'status': 'approved'
                }
            }
        }
    }
}

# De-nest children nodes for Discovery mode
def flatten_streams():
    flat_streams = {}
    # Loop through parents
    for stream_name, endpoint_config in STREAMS.items():
        flat_streams[stream_name] = endpoint_config
        # Loop through children
        children = endpoint_config.get('children')
        if children:
            for child_stream_name, child_endpoint_config in children.items():
                flat_streams[child_stream_name] = child_endpoint_config
                flat_streams[child_stream_name]['parent_stream'] = stream_name
                # Loop through grandchildren
                grandchildren = child_endpoint_config.get('children')
                if grandchildren:
                    for grandchild_stream_name, grandchild_endpoint_config in grandchildren.items():
                        flat_streams[grandchild_stream_name] = grandchild_endpoint_config
                        flat_streams[grandchild_stream_name]['parent_stream'] = child_stream_name
                        flat_streams[grandchild_stream_name]['grandparent_stream'] = stream_name
                        # Loop through great_grandchildren
                        great_grandchildren = grandchild_endpoint_config.get('children')
                        if great_grandchildren:
                            for great_grandchild_stream_name, great_grandchild_endpoint_config in great_grandchildren.items():
                                flat_streams[great_grandchild_stream_name] = great_grandchild_endpoint_config
                                flat_streams[great_grandchild_stream_name]['parent_stream'] = grandchild_stream_name
                                flat_streams[grandchild_stream_name]['grandparent_stream'] = child_stream_name
                                flat_streams[grandchild_stream_name]['great_grandparent_stream'] = stream_name

    return flat_streams