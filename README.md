# tap-awin-advertiser

⚠️ Deprecated, please use Airbyte [source-awin connector](https://github.com/airbytehq/airbyte/pull/21116) instead.

This is a [Singer](https://singer.io) tap that produces JSON-formatted data following the [Singer spec](https://github.com/singer-io/getting-started/blob/master/SPEC.md).

This tap retrieves data from the AWIN [Advertiser API](https://wiki.awin.com/index.php/Advertiser_API)

## Configuration

See file `sample_config.json`.

Overview over the possible config properties:

| Config property      | Required / Default value | Description
| -------------------- | ------------------------ | -----------
| `attribution_window` | No, default: `30`        | The attribution window in days for stream `transactions`. Before synchronizing you should make sure that transactions in this timeframe are removed from the destination table or you need to make sure that they are updated based on the primary key.
| `start_date`         | No                       | For streams with replication method INCREMENTAL the start date time to be used
| `oauth2_token`       | Yes                      | Your OAuth access token
| `user_agent`         | No                       | User agent to be used for HTTP requests
