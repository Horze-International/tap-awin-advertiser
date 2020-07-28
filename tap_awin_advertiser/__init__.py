#!/usr/bin/env python3
import sys
import json
import requests

import singer

from tap_awin_advertiser.client import AwinClient
from tap_awin_advertiser.discover import discover
from tap_awin_advertiser.sync import sync

LOGGER = singer.get_logger()

REQUIRED_CONFIG_KEYS = [
    'oauth2_token'
]

def do_discover():
    LOGGER.info('Starting discover')
    catalog = discover()
    json.dump(catalog.to_dict(), sys.stdout, indent=2)
    LOGGER.info('Finished discover')

@singer.utils.handle_top_exception(LOGGER)
def main():

    parsed_args = singer.utils.parse_args(REQUIRED_CONFIG_KEYS)

    with AwinClient(parsed_args.config['oauth2_token'],
                    parsed_args.config['user_agent']) as client:

        state = {}
        if parsed_args.state:
            state = parsed_args.state

        config = {}
        if parsed_args.config:
            config = parsed_args.config

        if parsed_args.discover:
            do_discover()
        elif parsed_args.catalog:
            sync(client=client,
                 config=config,
                 catalog=parsed_args.catalog,
                 state=state)

if __name__ == '__main__':
    main()
