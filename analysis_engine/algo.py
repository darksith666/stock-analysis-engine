"""
Algorithms automatically provide the following
member variables to any custom algorithm that derives
the ``analysis_engine.algo.BaseAlgo.process`` method.

By deriving the ``process()`` member method using an inherited
class, you can quickly build algorithms that
determine **buy** and **sell** conditions from
any of the automatically extracted
datasets from the redis pipeline:

- ``self.df_daily``
- ``self.df_minute``
- ``self.df_calls``
- ``self.df_puts``
- ``self.df_quote``
- ``self.df_pricing``
- ``self.df_stats``
- ``self.df_peers``
- ``self.df_iex_news``
- ``self.df_financials``
- ``self.df_earnings``
- ``self.df_dividends``
- ``self.df_company``
- ``self.df_yahoo_news``

**Recent Pricing Information**

- ``self.latest_close``
- ``self.latest_high``
- ``self.latest_open``
- ``self.latest_low``
- ``self.latest_volume``
- ``self.today_close``
- ``self.today_high``
- ``self.today_open``
- ``self.today_low``
- ``self.today_volume``
- ``self.ask``
- ``self.bid``

**Latest Backtest Date and Intraday Minute**

- ``self.latest_min``
- ``self.backtest_date``

.. note:: **self.latest_min** - Latest minute row in ``self.df_minute``

.. note:: **self.backtest_date** - Latest dataset date which is considered the
    backtest date for historical testing with the data pipeline
    structure (it's the ``date`` key in the dataset node root level)

**Balance Information**

- ``self.balance``
- ``self.prev_bal``

.. note:: If a key is not in the dataset, the
    algorithms's member variable will be an empty
    pandas DataFrame created with: ``pd.DataFrame([])``
    except ``self.pricing`` which is just a dictionary.
    Please ensure the engine successfully fetched
    and cached the dataset in redis using a tool like
    ``redis-cli`` and a query of ``keys *`` or
    ``keys <TICKER>_*`` on large deployments.

**Supported environment variables**

::

    # to show debug, trace logging please export ``SHARED_LOG_CFG``
    # to a debug logger json file. To turn on debugging for this
    # library, you can export this variable to the repo's
    # included file with the command:
    export SHARED_LOG_CFG=/opt/sa/analysis_engine/log/debug-logging.json
"""

import os
import json
import pandas as pd
import analysis_engine.consts as ae_consts
import analysis_engine.utils as ae_utils
import analysis_engine.build_trade_history_entry as history_utils
import analysis_engine.build_buy_order as buy_utils
import analysis_engine.build_sell_order as sell_utils
import analysis_engine.publish as publish
import analysis_engine.build_publish_request as build_publish_request
import analysis_engine.load_dataset as load_dataset
import analysis_engine.indicators.indicator_processor as ind_processor
import spylunking.log.setup_logging as log_utils

log = log_utils.build_colorized_logger(name=__name__)


class BaseAlgo:
    """BaseAlgo

    Run an algorithm against multiple tickers at once through the
    redis dataframe pipeline provided by
    `analysis_engine.extract.extract
    <https://github.com/AlgoTraders/stock-analysis-engine/bl
    ob/master/analysis_engine/extract.py>`__.

    **Data Pipeline Structure**

    This algorithm can handle an extracted dictionary with structure:

    .. code-block:: python

        import pandas as pd
        from analysis_engine.algo import BaseAlgo
        ticker = 'SPY'
        demo_algo = BaseAlgo(
            ticker=ticker,
            balance=1000.00,
            commission=6.00,
            name='test-{}'.format(ticker))
        date = '2018-11-05'
        dataset_id = '{}_{}'.format(
            ticker,
            date)
        # mock the data pipeline in redis:
        data = {
            ticker: [
                {
                    'id': dataset_id,
                    'date': date,
                    'data': {
                        'daily': pd.DataFrame([
                            {
                                'high': 280.01,
                                'low': 270.01,
                                'open': 275.01,
                                'close': 272.02,
                                'volume': 123,
                                'date': '2018-11-01 15:59:59'
                            },
                            {
                                'high': 281.01,
                                'low': 271.01,
                                'open': 276.01,
                                'close': 273.02,
                                'volume': 124,
                                'date': '2018-11-02 15:59:59'
                            },
                            {
                                'high': 282.01,
                                'low': 272.01,
                                'open': 277.01,
                                'close': 274.02,
                                'volume': 121,
                                'date': '2018-11-05 15:59:59'
                            }
                        ]),
                        'calls': pd.DataFrame([]),
                        'puts': pd.DataFrame([]),
                        'minute': pd.DataFrame([]),
                        'pricing': pd.DataFrame([]),
                        'quote': pd.DataFrame([]),
                        'news': pd.DataFrame([]),
                        'news1': pd.DataFrame([]),
                        'dividends': pd.DataFrame([]),
                        'earnings': pd.DataFrame([]),
                        'financials': pd.DataFrame([]),
                        'stats': pd.DataFrame([]),
                        'peers': pd.DataFrame([]),
                        'company': pd.DataFrame([])
                    }
                }
            ]
        }

        # run the algorithm
        demo_algo.handle_data(data=data)

        # get the algorithm results
        results = demo_algo.get_result()

        print(results)
    """

    def __init__(
            self,
            ticker=None,
            balance=5000.0,
            commission=6.0,
            tickers=None,
            name=None,
            use_key=None,
            auto_fill=True,
            version=1,
            config_file=None,
            config_dict=None,
            output_dir=None,
            publish_to_slack=False,
            publish_to_s3=False,
            publish_to_redis=False,
            publish_input=True,
            publish_history=True,
            publish_report=True,
            load_from_s3_bucket=None,
            load_from_s3_key=None,
            load_from_redis_key=None,
            load_from_file=None,
            load_compress=False,
            load_publish=True,
            load_config=None,
            report_redis_key=None,
            report_s3_bucket=None,
            report_s3_key=None,
            report_file=None,
            report_compress=False,
            report_publish=True,
            report_config=None,
            history_redis_key=None,
            history_s3_bucket=None,
            history_s3_key=None,
            history_file=None,
            history_compress=False,
            history_publish=True,
            history_config=None,
            extract_redis_key=None,
            extract_s3_bucket=None,
            extract_s3_key=None,
            extract_file=None,
            extract_save_dir=None,
            extract_compress=False,
            extract_publish=True,
            extract_config=None,
            dataset_type=ae_consts.SA_DATASET_TYPE_ALGO_READY,
            serialize_datasets=ae_consts.DEFAULT_SERIALIZED_DATASETS,
            raise_on_err=False,
            **kwargs):
        """__init__

        Build an analysis algorithm

        Use an algorithm object to:

        1) `Generate algorithm-ready datasets <https://gith
        ub.com/AlgoTraders/stock-analysis-engine#extra
        ct-algorithm-ready-datasets>`__
        2) Backtest trading theories with offline
        3) Issue trading alerts from the latest fetched datasets

        **(Optional) Trading Parameters**

        :param ticker: single ticker string
        :param balance: starting capital balance
            (default is ``5000.00``)
        :param commission: cost for commission
            for a single buy or sell trade
        :param tickers: optional - list of ticker strings
        :param name: optional - log tracking name
            or algo name
        :param use_key: optional - key for saving output
            in s3, redis, file
        :param auto_fill: optional - boolean for auto filling
            buy and sell orders for backtesting (default is
            ``True``)
        :param version: optional - version tracking
            value (default is ``1``)

        **Derived Config Loading for Indicators and Custom Backtest Values**

        :param config_file: path to a json file
            containing custom algorithm object
            member values (like indicator configuration and
            predict future date units ahead for a backtest)
        :param config_dict: optional - dictionary that
            can be passed to derived class implementations
            of: ``def load_from_config(config_dict=config_dict)``

        **Run a Backtest with an Algorithm-Ready Dataset in S3,
        Redis or a File**

        Use these arguments to load algorithm-ready datasets
        from supported sources (s3, redis or a file)

        :param load_from_s3_bucket: optional - string load the algo from an
            a previously-created s3 bucket holding an s3 key with an
            algorithm-ready dataset for use with:
            ``handle_data``
        :param load_from_s3_key: optional - string load the algo from an
            a previously-created s3 key holding an
            algorithm-ready dataset for use with:
            ``handle_data``
        :param load_from_redis_key: optional - string load the algo from a
            a previously-created redis key holding an
            algorithm-ready dataset for use with:
            ``handle_data``
        :param load_from_file: optional - string path to
            a previously-created local file holding an
            algorithm-ready dataset for use with:
            ``handle_data``
        :param load_compress: optional - boolean
            flag for toggling to decompress
            or not when loading an algorithm-ready
            dataset (``True`` means the dataset
            must be decompressed to load correctly inside
            an algorithm to run a backtest)
        :param load_publish: boolean - toggle publishing
            the load progress to slack, s3, redis or a file
            (default is ``True``)
        :param load_config: optional - dictionary
            for setting member variables to load
            an algorithm-ready dataset for backtesting
            (used by ``run_custom_algo``)

        **Algorithm Trade History Arguments**

        :param history_redis_key: optional - string
            where the algorithm trading history will be stored in
            an redis key
        :param history_s3_bucket: optional - string
            where the algorithm trading history will be stored in
            an s3 bucket
        :param history_s3_key: optional - string
            where the algorithm trading history will be stored in
            an s3 key
        :param history_file: optional - string file path for saving
            the ``trading history``
        :param history_compress: optional - boolean
            flag for toggling to decompress
            or not when loading an algorithm-ready
            dataset (``True`` means the dataset
            will be compressed on publish)
        :param history_publish: boolean - toggle publishing
            the history to s3, redis or a file
            (default is ``True``)
        :param history_config: optional - dictionary
            for setting member variables to publish
            an algo ``trade history``
            to s3, redis, a file or slack
            (used by ``run_custom_algo``)

        **Algorithm Trade Performance Report Arguments (Output Dataset)**

        :param report_redis_key: optional - string
            where the algorithm ``trading performance report`` (report)
            will be stored in an redis key
        :param report_s3_bucket: optional - string
            where the algorithm report will be stored in
            an s3 bucket
        :param report_s3_key: optional - string
            where the algorithm report will be stored in
            an s3 key
        :param report_file: optional - string file path for saving
            the ``trading performance report``
        :param report_compress: optional - boolean
            flag for toggling to decompress
            or not when loading an algorithm-ready
            dataset (``True`` means the dataset
            will be compressed on publish)
        :param report_publish: boolean - toggle publishing
            the ``trading performance report`` s3, redis or a file
            (default is ``True``)
        :param report_config: optional - dictionary
            for setting member variables to publish
            an algo ``result`` or
            ``trading performance report``
            to s3, redis, a file or slack
            (used by ``run_custom_algo``)

        **Extract an Algorithm-Ready Dataset Arguments**

        :param extract_redis_key: optional - string
            where the algorithm report will be stored in
            an redis key
        :param extract_s3_bucket: optional - string
            where the algorithm report will be stored in
            an s3 bucket
        :param extract_s3_key: optional - string
            where the algorithm report will be stored in
            an s3 key
        :param extract_file: optional - string file path for saving
            the processed datasets as an``algorithm-ready`` dataset
        :param extract_save_dir: optional - string path to
            auto-generated files from the algo
        :param extract_compress: optional - boolean
            flag for toggling to decompress
            or not when loading an algorithm-ready
            dataset (``True`` means the dataset
            will be compressed on publish)
        :param extract_publish: boolean - toggle publishing
            the used ``algorithm-ready dataset`` to s3, redis or a file
            (default is ``True``)
        :param extract_config: optional - dictionary
            for setting member variables to publish
            an algo ``input`` dataset (the contents of ``data``
            from ``self.handle_data(data=data)``
            (used by ``run_custom_algo``)

        **Dataset Arguments**

        :param dataset_type: optional - dataset type
            (default is ``ae_consts.SA_DATASET_TYPE_ALGO_READY``)
        :param serialize_datasets: optional - list of dataset names to
            deserialize in the dataset
            (default is ``ae_consts.DEFAULT_SERIALIZED_DATASETS``)
        :param encoding: optional - string for data encoding

        **(Optional) Publishing arguments**

        :param publish_to_slack: optional - boolean for
            publishing to slack (default is ``False``)
        :param publish_to_s3: optional - boolean for
            publishing to s3 (default is ``False``)
        :param publish_to_redis: optional - boolean for
            publishing to redis (default is ``False``)
        :param publish_input: boolean - toggle publishing
            all input datasets to s3 and redis
            (default ``True``)
        :param publish_history: boolean - toggle publishing
            the history to s3 and redis
            (default ``True``)
        :param publish_report: boolean - toggle publishing
            any generated datasets to s3 and redis
            (default ``True``)

        **Debugging arguments**

        :param raise_on_err: optional - boolean for
            unittests and developing algorithms with the
            ``analysis_engine.run_algo.run_algo`` helper.
            .. note:: When set to ``True`` exceptions will
                are raised to the calling functions
        :param output_dir: optional - string path to
            auto-generated files from the algo

        **Future Argument Placeholder**

        :param kwargs: optional - dictionary of keyword
            arguments
        """
        self.buys = []
        self.sells = []
        self.num_shares = 0
        self.tickers = tickers
        if not self.tickers:
            if ticker:
                self.tickers = [
                    ticker.upper()
                ]
            else:
                raise Exception('BaseAlgo - please set a ticker to use')
        self.balance = balance
        self.starting_balance = balance
        self.starting_close = 0.0
        self.trade_horizon_units = ae_consts.ALGO_HORIZON_UNITS_DAY
        self.trade_horizon = 5
        self.commission = commission
        self.result = None
        self.name = name
        self.num_owned = None
        self.num_buys = None
        self.num_sells = None
        self.trade_price = 0.0
        self.today_high = 0.0
        self.today_low = 0.0
        self.today_open = 0.0
        self.today_close = 0.0
        self.today_volume = 0
        self.latest_close = 0.0
        self.latest_high = 0.0
        self.latest_open = 0.0
        self.latest_low = 0.0
        self.latest_volume = 0
        self.latest_min = None
        self.backtest_date = None
        self.ask = 0.0
        self.bid = 0.0
        self.prev_bal = None
        self.prev_num_owned = None
        self.ds_id = None
        self.trade_date = None
        self.trade_type = ae_consts.TRADE_SHARES
        self.buy_hold_units = 20
        self.sell_hold_units = 20
        self.spread_exp_date = None
        self.last_close = None
        self.order_history = []
        self.config_file = config_file
        self.config_dict = config_dict
        self.positions = {}
        self.created_date = ae_utils.utc_now_str()
        self.created_buy = False
        self.should_buy = False
        self.buy_strength = None
        self.buy_risk = None
        self.created_sell = False
        self.should_sell = False
        self.sell_strength = None
        self.sell_risk = None
        self.stop_loss = None
        self.trailing_stop_loss = None

        self.last_handle_data = None
        self.last_ds_id = None
        self.last_ds_date = None
        self.last_ds_data = None

        self.ds_date = None
        self.ds_data = None
        self.df_daily = pd.DataFrame([{}])
        self.df_minute = pd.DataFrame([{}])
        self.df_stats = pd.DataFrame([{}])
        self.df_peers = pd.DataFrame([{}])
        self.df_financials = pd.DataFrame([])
        self.df_earnings = pd.DataFrame([{}])
        self.df_dividends = pd.DataFrame([{}])
        self.df_quote = pd.DataFrame([{}])
        self.df_company = pd.DataFrame([{}])
        self.df_iex_news = pd.DataFrame([{}])
        self.df_yahoo_news = pd.DataFrame([{}])
        self.df_calls = pd.DataFrame([{}])
        self.df_puts = pd.DataFrame([{}])
        self.df_pricing = pd.DataFrame([{}])
        self.empty_pd = pd.DataFrame([{}])
        self.empty_pd_str = ae_consts.EMPTY_DF_STR

        self.note = None
        self.debug_msg = ''
        self.version = version
        self.verbose = ae_consts.ev(
            'AE_DEBUG',
            '1') == '1'

        self.publish_to_slack = publish_to_slack
        self.publish_to_s3 = publish_to_s3
        self.publish_to_redis = publish_to_redis
        self.publish_history = publish_history
        self.publish_report = publish_report
        self.publish_input = publish_input
        self.raise_on_err = raise_on_err

        if not self.publish_to_s3:
            self.publish_to_s3 = ae_consts.ENABLED_S3_UPLOAD
        if not self.publish_to_redis:
            self.publish_to_redis = ae_consts.ENABLED_REDIS_PUBLISH

        self.output_file_dir = None
        self.output_file_prefix = None

        if self.raise_on_err:
            if self.tickers and len(self.tickers):
                self.output_file_prefix = str(
                    self.tickers[0]).upper()
            self.output_file_dir = '/opt/sa/tests/datasets/algo'

        if not self.name:
            self.name = 'myalgo'

        """
        Load tracking connectivity for recording
        - input
        - trade history
        - algorithm-generated datasets
        """

        # parse optional input args
        self.save_as_key = use_key
        if not self.save_as_key:
            self.save_as_key = '{}-{}'.format(
                self.name.replace(' ', ''),
                ae_utils.utc_now_str(fmt='%Y-%m-%d-%H-%M-%S.%f'))
        self.output_file_dir = '/opt/sa/tests/datasets/algo'
        if not output_dir:
            self.output_file_dir = output_dir

        # set up default keys
        self.default_output_file = '{}/{}.json'.format(
            self.output_file_dir,
            self.save_as_key)
        self.default_s3_key = '{}.json'.format(
            self.save_as_key)
        self.default_redis_key = '{}'.format(
            self.save_as_key)

        self.default_load_output_file = '{}/ready-{}.json'.format(
            self.output_file_dir,
            self.save_as_key)
        self.default_history_output_file = '{}/history-{}.json'.format(
            self.output_file_dir,
            self.save_as_key)
        self.default_report_output_file = '{}/report-{}.json'.format(
            self.output_file_dir,
            self.save_as_key)
        self.default_extract_output_file = '{}/extract-{}.json'.format(
            self.output_file_dir,
            self.save_as_key)

        self.default_load_redis_key = 'algo:ready:{}'.format(
            self.default_redis_key)
        self.default_history_redis_key = 'algo:history:{}'.format(
            self.default_redis_key)
        self.default_report_redis_key = 'algo:output:{}'.format(
            self.default_redis_key)
        self.default_extract_redis_key = 'algo:extract:{}'.format(
            self.default_redis_key)

        if not load_config:
            load_config = build_publish_request.build_publish_request()
        if not extract_config:
            extract_config = build_publish_request.build_publish_request()
        if not history_config:
            history_config = build_publish_request.build_publish_request()
        if not report_config:
            report_config = build_publish_request.build_publish_request()

        if not load_from_s3_bucket:
            load_from_s3_bucket = ae_consts.ALGO_READY_DATASET_S3_BUCKET_NAME
        if not extract_s3_bucket:
            extract_s3_bucket = ae_consts.ALGO_EXTRACT_DATASET_S3_BUCKET_NAME
        if not history_s3_bucket:
            history_s3_bucket = ae_consts.ALGO_HISTORY_DATASET_S3_BUCKET_NAME
        if not report_s3_bucket:
            report_s3_bucket = ae_consts.ALGO_REPORT_DATASET_S3_BUCKET_NAME

        # Load the input dataset publishing member variables
        self.extract_output_dir = extract_config.get(
            'output_dir', None)
        self.extract_output_file = extract_config.get(
            'output_file', None)
        self.extract_label = extract_config.get(
            'label', self.name)
        self.extract_convert_to_json = extract_config.get(
            'convert_to_json', True)
        self.extract_compress = extract_config.get(
            'compress', ae_consts.ALGO_INPUT_COMPRESS)
        self.extract_redis_enabled = extract_config.get(
            'redis_enabled', False)
        self.extract_redis_address = extract_config.get(
            'redis_address', ae_consts.ENABLED_S3_UPLOAD)
        self.extract_redis_db = extract_config.get(
            'redis_db', ae_consts.REDIS_DB)
        self.extract_redis_password = extract_config.get(
            'redis_password', ae_consts.REDIS_PASSWORD)
        self.extract_redis_expire = extract_config.get(
            'redis_expire', ae_consts.REDIS_EXPIRE)
        self.extract_redis_serializer = extract_config.get(
            'redis_serializer', 'json')
        self.extract_redis_encoding = extract_config.get(
            'redis_encoding', 'utf-8')
        self.extract_s3_enabled = extract_config.get(
            's3_enabled', False)
        self.extract_s3_address = extract_config.get(
            's3_address', ae_consts.S3_ADDRESS)
        self.extract_s3_bucket = extract_config.get(
            's3_bucket', extract_s3_bucket)
        self.extract_s3_access_key = extract_config.get(
            's3_access_key', ae_consts.S3_ACCESS_KEY)
        self.extract_s3_secret_key = extract_config.get(
            's3_secret_key', ae_consts.S3_SECRET_KEY)
        self.extract_s3_region_name = extract_config.get(
            's3_region_name', ae_consts.S3_REGION_NAME)
        self.extract_s3_secure = extract_config.get(
            's3_secure', ae_consts.S3_SECURE)
        self.extract_slack_enabled = extract_config.get(
            'slack_enabled', False)
        self.extract_slack_code_block = extract_config.get(
            'slack_code_block', False)
        self.extract_slack_full_width = extract_config.get(
            'slack_full_width', False)
        self.extract_redis_key = extract_config.get(
            'redis_key', extract_redis_key)
        self.extract_s3_key = extract_config.get(
            's3_key', extract_s3_key)
        self.extract_verbose = extract_config.get(
            'verbose', False)

        # load the trade history publishing member variables
        self.history_output_dir = history_config.get(
            'output_dir', None)
        self.history_output_file = history_config.get(
            'output_file', None)
        self.history_label = history_config.get(
            'label', self.name)
        self.history_convert_to_json = history_config.get(
            'convert_to_json', True)
        self.history_compress = history_config.get(
            'compress', ae_consts.ALGO_HISTORY_COMPRESS)
        self.history_redis_enabled = history_config.get(
            'redis_enabled', False)
        self.history_redis_address = history_config.get(
            'redis_address', ae_consts.ENABLED_S3_UPLOAD)
        self.history_redis_db = history_config.get(
            'redis_db', ae_consts.REDIS_DB)
        self.history_redis_password = history_config.get(
            'redis_password', ae_consts.REDIS_PASSWORD)
        self.history_redis_expire = history_config.get(
            'redis_expire', ae_consts.REDIS_EXPIRE)
        self.history_redis_serializer = history_config.get(
            'redis_serializer', 'json')
        self.history_redis_encoding = history_config.get(
            'redis_encoding', 'utf-8')
        self.history_s3_enabled = history_config.get(
            's3_enabled', False)
        self.history_s3_address = history_config.get(
            's3_address', ae_consts.S3_ADDRESS)
        self.history_s3_bucket = history_config.get(
            's3_bucket', history_s3_bucket)
        self.history_s3_access_key = history_config.get(
            's3_access_key', ae_consts.S3_ACCESS_KEY)
        self.history_s3_secret_key = history_config.get(
            's3_secret_key', ae_consts.S3_SECRET_KEY)
        self.history_s3_region_name = history_config.get(
            's3_region_name', ae_consts.S3_REGION_NAME)
        self.history_s3_secure = history_config.get(
            's3_secure', ae_consts.S3_SECURE)
        self.history_slack_enabled = history_config.get(
            'slack_enabled', False)
        self.history_slack_code_block = history_config.get(
            'slack_code_block', False)
        self.history_slack_full_width = history_config.get(
            'slack_full_width', False)
        self.history_redis_key = history_config.get(
            'redis_key', history_redis_key)
        self.history_s3_key = history_config.get(
            's3_key', history_s3_key)
        self.history_verbose = history_config.get(
            'verbose', False)

        # Load publishing for algorithm-generated report member variables
        self.report_output_dir = report_config.get(
            'output_dir', None)
        self.report_output_file = report_config.get(
            'output_file', None)
        self.report_label = report_config.get(
            'label', self.name)
        self.report_convert_to_json = report_config.get(
            'convert_to_json', True)
        self.report_compress = report_config.get(
            'compress', ae_consts.ALGO_REPORT_COMPRESS)
        self.report_redis_enabled = report_config.get(
            'redis_enabled', False)
        self.report_redis_address = report_config.get(
            'redis_address', ae_consts.ENABLED_S3_UPLOAD)
        self.report_redis_db = report_config.get(
            'redis_db', ae_consts.REDIS_DB)
        self.report_redis_password = report_config.get(
            'redis_password', ae_consts.REDIS_PASSWORD)
        self.report_redis_expire = report_config.get(
            'redis_expire', ae_consts.REDIS_EXPIRE)
        self.report_redis_serializer = report_config.get(
            'redis_serializer', 'json')
        self.report_redis_encoding = report_config.get(
            'redis_encoding', 'utf-8')
        self.report_s3_enabled = report_config.get(
            's3_enabled', False)
        self.report_s3_address = report_config.get(
            's3_address', ae_consts.S3_ADDRESS)
        self.report_s3_bucket = report_config.get(
            's3_bucket', report_s3_bucket)
        self.report_s3_access_key = report_config.get(
            's3_access_key', ae_consts.S3_ACCESS_KEY)
        self.report_s3_secret_key = report_config.get(
            's3_secret_key', ae_consts.S3_SECRET_KEY)
        self.report_s3_region_name = report_config.get(
            's3_region_name', ae_consts.S3_REGION_NAME)
        self.report_s3_secure = report_config.get(
            's3_secure', ae_consts.S3_SECURE)
        self.report_slack_enabled = report_config.get(
            'slack_enabled', False)
        self.report_slack_code_block = report_config.get(
            'slack_code_block', False)
        self.report_slack_full_width = report_config.get(
            'slack_full_width', False)
        self.report_redis_key = report_config.get(
            'redis_key', report_redis_key)
        self.report_s3_key = report_config.get(
            's3_key', report_s3_key)
        self.report_verbose = report_config.get(
            'verbose', False)

        self.loaded_dataset = None

        # load the algorithm-ready dataset input member variables
        self.dsload_output_dir = load_config.get(
            'output_dir', None)
        self.dsload_output_file = load_config.get(
            'output_file', None)
        self.dsload_label = load_config.get(
            'label', self.name)
        self.dsload_convert_to_json = load_config.get(
            'convert_to_json', True)
        self.dsload_compress = load_config.get(
            'compress', load_compress)
        self.dsload_redis_enabled = load_config.get(
            'redis_enabled', False)
        self.dsload_redis_address = load_config.get(
            'redis_address', ae_consts.ENABLED_S3_UPLOAD)
        self.dsload_redis_db = load_config.get(
            'redis_db', ae_consts.REDIS_DB)
        self.dsload_redis_password = load_config.get(
            'redis_password', ae_consts.REDIS_PASSWORD)
        self.dsload_redis_expire = load_config.get(
            'redis_expire', ae_consts.REDIS_EXPIRE)
        self.dsload_redis_serializer = load_config.get(
            'redis_serializer', 'json')
        self.dsload_redis_encoding = load_config.get(
            'redis_encoding', 'utf-8')
        self.dsload_s3_enabled = load_config.get(
            's3_enabled', False)
        self.dsload_s3_address = load_config.get(
            's3_address', ae_consts.S3_ADDRESS)
        self.dsload_s3_bucket = load_config.get(
            's3_bucket', load_from_s3_bucket)
        self.dsload_s3_access_key = load_config.get(
            's3_access_key', ae_consts.S3_ACCESS_KEY)
        self.dsload_s3_secret_key = load_config.get(
            's3_secret_key', ae_consts.S3_SECRET_KEY)
        self.dsload_s3_region_name = load_config.get(
            's3_region_name', ae_consts.S3_REGION_NAME)
        self.dsload_s3_secure = load_config.get(
            's3_secure', ae_consts.S3_SECURE)
        self.dsload_slack_enabled = load_config.get(
            'slack_enabled', False)
        self.dsload_slack_code_block = load_config.get(
            'slack_code_block', False)
        self.dsload_slack_full_width = load_config.get(
            'slack_full_width', False)
        self.dsload_redis_key = load_config.get(
            'redis_key', load_from_redis_key)
        self.dsload_s3_key = load_config.get(
            's3_key', load_from_s3_key)
        self.dsload_verbose = load_config.get(
            'verbose', False)

        self.load_from_external_source()

        if self.config_dict:
            val = self.config_dict.get(
                'trade_horizon_units',
                'day').lower()
            if val == 'day':
                self.horizon_units = ae_consts.ALGO_HORIZON_UNITS_DAY
            else:
                self.horizon_units = ae_consts.ALGO_HORIZON_UNITS_MINUTE
            self.trade_horizon = int(self.config_dict.get(
                'trade_horizon',
                5))
        # end of loading initial values from a config_dict before derived

        self.iproc = None
        self.iproc = self.get_indicator_processor()
        self.iproc_label = 'no-iproc-label'
        self.num_indicators = 0

        self.load_from_config(
            config_dict=config_dict)

        if self.iproc:
            if not hasattr(self.iproc, 'process'):
                raise Exception(
                    '{} - Please implement a process methond in the '
                    'IndicatorProcessor - the current object={} '
                    'is missing one. Please refer to the example: '
                    'https://github.com/AlgoTraders/stock-analys'
                    'is-engine/blob/master/analysis_engine/indica'
                    'tors/indicator_processor.py'.format(
                        self.name,
                        self.iproc))
            self.iproc_label = self.iproc.get_label()
            self.num_indicators = self.iproc.get_num_indicators()
    # end of __init__

    def get_indicator_processor(
            self,
            existing_processor=None):
        """get_indicator_processor

        singleton for getting the indicator processor

        :param existing_processor: allow derived algos
            to build their own indicator
            processor and pass it to the base
        """
        if existing_processor:
            log.info(
                '{} - loading existing processor={}'.format(
                    self.name,
                    existing_processor.get_name()))
            self.iproc = existing_processor
        else:
            if self.iproc:
                return self.iproc

            if not self.config_dict:
                log.info(
                    '{} - is missing an algorithm config_dict '
                    'please add one to run indicators'.format(
                        self.name))
            else:
                self.iproc = ind_processor.IndicatorProcessor(
                    config_dict=self.config_dict,
                    label='{}-prc'.format(
                        self.name),
                    verbose=self.verbose)
        # if use new or existing

        return self.iproc
    # end of get_indicator_processor

    def process(
            self,
            algo_id,
            ticker,
            dataset):
        """process

        Derive custom algorithm buy and sell conditions
        before placing orders. Just implement your own
        ``process`` method.

        :param algo_id: string - algo identifier label for debugging datasets
            during specific dates
        :param ticker: string - ticker
        :param dataset: a dictionary of identifiers (for debugging) and
            multiple pandas ``pd.DataFrame`` objects. Dictionary where keys
            represent a label from one of the data sources (``IEX``,
            ``Yahoo``, ``FinViz`` or other). Here is the supported
            dataset structure for the process method:

            .. note:: There are no required keys for ``data``, the list
                below is not hard-enforced by default. This is just
                a reference for what is available with the v1 engine.

            ::

                dataset = {
                    'id': <string TICKER_DATE - redis cache key>,
                    'date': <string DATE>,
                    'data': {
                        'daily': pd.DataFrame([]),
                        'minute': pd.DataFrame([]),
                        'quote': pd.DataFrame([]),
                        'stats': pd.DataFrame([]),
                        'peers': pd.DataFrame([]),
                        'news1': pd.DataFrame([]),
                        'financials': pd.DataFrame([]),
                        'earnings': pd.DataFrame([]),
                        'dividends': pd.DataFrame([]),
                        'calls': pd.DataFrame([]),
                        'puts': pd.DataFrame([]),
                        'pricing': pd.DataFrame([]),
                        'news': pd.DataFrame([])
                    }
                }

            example:

            ::

                dataset = {
                    'id': 'SPY_2018-11-02
                    'date': '2018-11-02',
                    'data': {
                        'daily': pd.DataFrame,
                        'minute': pd.DataFrame,
                        'calls': pd.DataFrame,
                        'puts': pd.DataFrame,
                        'news': pd.DataFrame
                    }
                }
        """

        log.info(
            'process - ticker={} balance={} owned={} date={} '
            'high={} low={} open={} close={} vol={} '
            'comm={} '
            'buy_str={} buy_risk={} '
            'sell_str={} sell_risk={} '
            'num_buys={} num_sells={} '
            'id={}'.format(
                self.ticker,
                self.balance,
                self.num_owned,
                self.trade_date,
                self.latest_high,
                self.latest_low,
                self.latest_open,
                self.latest_close,
                self.latest_volume,
                self.commission,
                self.buy_strength,
                self.buy_risk,
                self.sell_strength,
                self.sell_risk,
                len(self.buys),
                len(self.sells),
                algo_id))

        # flip these on to sell/buy
        # buys will not FILL if there's not enough funds to buy
        # sells will not FILL if there's nothing already owned
        self.should_sell = False
        self.should_buy = False

        log.info(
            '{} - ready with process has df_daily rows={}'.format(
                self.name,
                len(self.df_daily.index)))

        """
        Want to iterate over daily pricing data
        to determine buys or sells from the:
        self.df_daily dataset fetched from IEX?

        # loop over the rows in the daily dataset:
        for idx, row in self.df_daily.iterrows():
            print(row)
        """

        if self.num_owned and self.should_sell:
            self.create_sell_order(
                ticker=ticker,
                row={
                    'name': algo_id,
                    'close': 270.0,
                    'date': '2018-11-02'
                },
                reason='testing')

        if self.should_buy:
            self.create_buy_order(
                ticker=ticker,
                row={
                    'name': algo_id,
                    'close': 270.0,
                    'date': '2018-11-02'
                },
                reason='testing')

        # if still owned and have not already created
        # a sell already
        # self.num_owned automatically updates on sell and buy orders
        if self.num_owned and not self.created_sell:
            self.create_sell_order(
                ticker=ticker,
                row={
                    'name': algo_id,
                    'close': 270.0,
                    'date': '2018-11-02'
                },
                reason='testing')

    # end of process

    def load_from_external_source(
            self,
            path_to_file=None,
            s3_bucket=None,
            s3_key=None,
            redis_key=None):
        """load_from_external_source

        Load an algorithm-ready dataset for ``handle_data`` backtesting
        and trade performance analysis from:

        - Local file
        - S3
        - Redis

        :param path_to_file: optional - path to local file
        :param s3_bucket: optional - s3 s3_bucket
        :param s3_key: optional - s3 key
        :param redis_key: optional - redis key
        """

        if path_to_file:
            self.dsload_output_file = path_to_file
        if s3_key:
            self.dsload_s3_key = s3_key
        if s3_bucket:
            self.dsload_s3_bucket = s3_bucket
            self.dsload_s3_enabled = True
        if redis_key:
            self.dsload_redis_key = redis_key
            self.dsload_redis_enabled = True

        if (self.dsload_s3_key and
                self.dsload_s3_bucket and
                self.dsload_s3_enabled and
                not self.loaded_dataset):
            self.debug_msg = (
                'external load START - s3={}:{}/{}'.format(
                    self.dsload_s3_address,
                    self.dsload_s3_bucket,
                    self.dsload_s3_key))
            log.info(self.debug_msg)
            self.loaded_dataset = load_dataset.load_dataset(
                s3_enabled=self.dsload_s3_enabled,
                s3_address=self.dsload_s3_address,
                s3_key=self.dsload_s3_key,
                s3_bucket=self.dsload_s3_bucket,
                s3_access_key=self.dsload_s3_access_key,
                s3_secret_key=self.dsload_s3_secret_key,
                s3_region_name=self.dsload_s3_region_name,
                s3_secure=self.dsload_s3_secure,
                compress=self.dsload_compress,
                encoding=self.dsload_redis_encoding)
            if self.loaded_dataset:
                self.debug_msg = (
                    'external load SUCCESS - s3={}:{}/{}'.format(
                        self.dsload_s3_address,
                        self.dsload_s3_bucket,
                        self.dsload_s3_key))
            else:
                self.debug_msg = (
                    'external load FAILED - s3={}:{}/{}'.format(
                        self.dsload_s3_address,
                        self.dsload_s3_bucket,
                        self.dsload_s3_key))
                log.error(self.debug_msg)
                raise Exception(self.debug_msg)
        elif (self.dsload_redis_key and
                self.dsload_redis_enabled and
                not self.loaded_dataset):
            self.debug_msg = (
                'external load START - redis={}:{}/{}'.format(
                    self.dsload_redis_address,
                    self.dsload_redis_db,
                    self.dsload_redis_key))
            log.debug(self.debug_msg)
            self.loaded_dataset = load_dataset.load_dataset(
                redis_enabled=self.dsload_redis_enabled,
                redis_address=self.dsload_redis_address,
                redis_key=self.dsload_redis_key,
                redis_db=self.dsload_redis_db,
                redis_password=self.dsload_redis_password,
                redis_expire=self.dsload_redis_expire,
                redis_serializer=self.dsload_redis_serializer,
                redis_encoding=self.dsload_redis_encoding,
                compress=self.dsload_compress,
                encoding=self.dsload_redis_encoding)
            if self.loaded_dataset:
                self.debug_msg = (
                    'external load SUCCESS - redis={}:{}/{}'.format(
                        self.dsload_redis_address,
                        self.dsload_redis_db,
                        self.dsload_redis_key))
            else:
                self.debug_msg = (
                    'external load FAILED - redis={}:{}/{}'.format(
                        self.dsload_redis_address,
                        self.dsload_redis_db,
                        self.dsload_redis_key))
                log.error(self.debug_msg)
                raise Exception(self.debug_msg)
        elif (self.dsload_output_file and
                not self.loaded_dataset):
            if os.path.exists(self.dsload_output_file):
                self.debug_msg = (
                    'external load START - file={}'.format(
                        self.dsload_output_file))
                log.debug(self.debug_msg)
                self.loaded_dataset = load_dataset.load_dataset(
                    path_to_file=self.dsload_output_file,
                    compress=self.dsload_compress,
                    encoding=self.extract_redis_encoding)
                if self.loaded_dataset:
                    self.debug_msg = (
                        'external load SUCCESS - file={}'.format(
                            self.dsload_output_file))
                else:
                    self.debug_msg = (
                        'external load FAILED - file={}'.format(
                            self.dsload_output_file))
                    log.error(self.debug_msg)
                    raise Exception(self.debug_msg)
            else:
                self.debug_msg = (
                    'external load - did not find file={}'.format(
                        self.dsload_output_file))
                log.error(self.debug_msg)
                raise Exception(self.debug_msg)
        # end of if supported external loader
        log.debug(
            'external load END')
    # end of load_from_external_source

    def publish_report_dataset(
            self,
            **kwargs):
        """publish_report_dataset

        publish trade history datasets to caches (redis), archives
        (minio s3), a local file (``output_file``) and slack

        :param kwargs: keyword argument dictionary
        :return: tuple: ``status``, ``output_file``
        """

        # parse optional input args
        output_file = kwargs.get(
            'output_file', None)
        label = kwargs.get(
            'label', self.name)
        convert_to_json = kwargs.get(
            'convert_to_json', self.report_convert_to_json)
        compress = kwargs.get(
            'compress', self.report_compress)
        redis_enabled = kwargs.get(
            'redis_enabled', False)
        redis_address = kwargs.get(
            'redis_address', self.report_redis_address)
        redis_db = kwargs.get(
            'redis_db', self.report_redis_db)
        redis_password = kwargs.get(
            'redis_password', self.report_redis_password)
        redis_expire = kwargs.get(
            'redis_expire', self.report_redis_expire)
        redis_serializer = kwargs.get(
            'redis_serializer', self.report_redis_serializer)
        redis_encoding = kwargs.get(
            'redis_encoding', self.report_redis_encoding)
        s3_enabled = kwargs.get(
            's3_enabled', False)
        s3_address = kwargs.get(
            's3_address', self.report_s3_address)
        s3_bucket = kwargs.get(
            's3_bucket', self.report_s3_bucket)
        s3_access_key = kwargs.get(
            's3_access_key', self.report_s3_access_key)
        s3_secret_key = kwargs.get(
            's3_secret_key', self.report_s3_secret_key)
        s3_region_name = kwargs.get(
            's3_region_name', self.report_s3_region_name)
        s3_secure = kwargs.get(
            's3_secure', self.report_s3_secure)
        slack_enabled = kwargs.get(
            'slack_enabled', self.report_slack_enabled)
        slack_code_block = kwargs.get(
            'slack_code_block', self.report_slack_code_block)
        slack_full_width = kwargs.get(
            'slack_full_width', self.report_slack_full_width)
        redis_key = kwargs.get(
            'redis_key', self.report_redis_key)
        s3_key = kwargs.get(
            's3_key', self.report_s3_key)
        verbose = kwargs.get(
            'verbose', self.report_verbose)

        status = ae_consts.NOT_RUN

        if not self.publish_report:
            log.info(
                'report publish - disabled - '
                '{} - tickers={}'.format(
                    self.name,
                    self.tickers))
            return status

        output_record = self.create_report_dataset()

        if output_file or s3_enabled or redis_enabled or slack_enabled:
            log.info(
                'report build json - {} - tickers={}'.format(
                    self.name,
                    self.tickers))
            use_data = json.dumps(output_record)
            num_bytes = len(use_data)
            num_mb = ae_consts.get_mb(num_bytes)
            log.info(
                'report publish - START - '
                '{} - tickers={} '
                'file={} size={}MB '
                's3={} s3_key={} '
                'redis={} redis_key={} '
                'slack={}'.format(
                    self.name,
                    self.tickers,
                    output_file,
                    num_mb,
                    s3_enabled,
                    s3_key,
                    redis_enabled,
                    redis_key,
                    slack_enabled))
            publish_status = publish.publish(
                data=use_data,
                label=label,
                convert_to_json=convert_to_json,
                output_file=output_file,
                compress=compress,
                redis_enabled=redis_enabled,
                redis_key=redis_key,
                redis_address=redis_address,
                redis_db=redis_db,
                redis_password=redis_password,
                redis_expire=redis_expire,
                redis_serializer=redis_serializer,
                redis_encoding=redis_encoding,
                s3_enabled=s3_enabled,
                s3_key=s3_key,
                s3_address=s3_address,
                s3_bucket=s3_bucket,
                s3_access_key=s3_access_key,
                s3_secret_key=s3_secret_key,
                s3_region_name=s3_region_name,
                s3_secure=s3_secure,
                slack_enabled=slack_enabled,
                slack_code_block=slack_code_block,
                slack_full_width=slack_full_width,
                verbose=verbose)

            status = publish_status

            log.info(
                'report publish - END - {} '
                '{} - tickers={} '
                'file={} s3={} redis={} size={}MB'.format(
                    ae_consts.get_status(status=status),
                    self.name,
                    self.tickers,
                    output_file,
                    s3_key,
                    redis_key,
                    num_mb))
        # end of handling for publish

        return status
    # end of publish_report_dataset

    def create_report_dataset(
            self):
        """create_report_dataset

        Create the ``Trading Performance Report`` dataset
        during the ``self.publish_input_dataset()`` member method.
        Inherited Algorithm classes can derive how they build a
        custom ``Trading Performance Report`` dataset before publishing
        by implementing this method in the derived class.
        """

        log.info('algo-ready - create start')

        data_for_tickers = self.get_supported_tickers_in_data(
            data=self.last_handle_data)

        num_tickers = len(data_for_tickers)
        if num_tickers > 0:
            self.debug_msg = (
                '{} handle - tickers={}'.format(
                    self.name,
                    json.dumps(data_for_tickers)))

        output_record = {}
        for ticker in data_for_tickers:
            if ticker not in output_record:
                output_record[ticker] = []
            num_ticker_datasets = len(self.last_handle_data[ticker])
            cur_idx = 1
            for idx, node in enumerate(self.last_handle_data[ticker]):
                track_label = self.build_progress_label(
                    progress=cur_idx,
                    total=num_ticker_datasets)
                algo_id = 'ticker={} {}'.format(
                    ticker,
                    track_label)
                log.info(
                    '{} convert - {} - ds={}'.format(
                        self.name,
                        algo_id,
                        node['date']))

                new_node = {
                    'id': node['id'],
                    'date': node['date'],
                    'data': {}
                }

                # parse the dataset node and set member variables
                self.debug_msg = (
                    '{} START - convert load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))
                self.load_from_dataset(
                    ds_data=node)
                for ds_key in node['data']:
                    empty_ds = self.empty_pd_str
                    data_val = node['data'][ds_key]
                    if ds_key not in new_node['data']:
                        new_node['data'][ds_key] = empty_ds
                    self.debug_msg = (
                        'convert node={} ds_key={}'.format(
                            node,
                            ds_key))
                    if hasattr(data_val, 'to_json'):
                        new_node['data'][ds_key] = data_val.to_json(
                            orient='records',
                            date_format='iso')
                    else:
                        if not data_val:
                            new_node['data'][ds_key] = empty_ds
                        else:
                            new_node['data'][ds_key] = json.dumps(
                                data_val)
                    # if/else
                # for all dataset values in data
                self.debug_msg = (
                    '{} END - convert load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))

                output_record[ticker].append(new_node)
                cur_idx += 1
            # end for all self.last_handle_data[ticker]
        # end of converting dataset

        return output_record
    # end of create_report_dataset

    def publish_trade_history_dataset(
            self,
            **kwargs):
        """publish_trade_history_dataset

        publish trade history datasets to caches (redis), archives
        (minio s3), a local file (``output_file``) and slack

        :param kwargs: keyword argument dictionary
        :return: tuple: ``status``, ``output_file``
        """

        # parse optional input args
        output_file = kwargs.get(
            'output_file', None)
        label = kwargs.get(
            'label', self.name)
        convert_to_json = kwargs.get(
            'convert_to_json', self.history_convert_to_json)
        compress = kwargs.get(
            'compress', self.history_compress)
        redis_enabled = kwargs.get(
            'redis_enabled', False)
        redis_address = kwargs.get(
            'redis_address', self.history_redis_address)
        redis_db = kwargs.get(
            'redis_db', self.history_redis_db)
        redis_password = kwargs.get(
            'redis_password', self.history_redis_password)
        redis_expire = kwargs.get(
            'redis_expire', self.history_redis_expire)
        redis_serializer = kwargs.get(
            'redis_serializer', self.history_redis_serializer)
        redis_encoding = kwargs.get(
            'redis_encoding', self.history_redis_encoding)
        s3_enabled = kwargs.get(
            's3_enabled', False)
        s3_address = kwargs.get(
            's3_address', self.history_s3_address)
        s3_bucket = kwargs.get(
            's3_bucket', self.history_s3_bucket)
        s3_access_key = kwargs.get(
            's3_access_key', self.history_s3_access_key)
        s3_secret_key = kwargs.get(
            's3_secret_key', self.history_s3_secret_key)
        s3_region_name = kwargs.get(
            's3_region_name', self.history_s3_region_name)
        s3_secure = kwargs.get(
            's3_secure', self.history_s3_secure)
        slack_enabled = kwargs.get(
            'slack_enabled', self.history_slack_enabled)
        slack_code_block = kwargs.get(
            'slack_code_block', self.history_slack_code_block)
        slack_full_width = kwargs.get(
            'slack_full_width', self.history_slack_full_width)
        redis_key = kwargs.get(
            'redis_key', self.history_redis_key)
        s3_key = kwargs.get(
            's3_key', self.history_s3_key)
        verbose = kwargs.get(
            'verbose', self.history_verbose)

        status = ae_consts.NOT_RUN

        if not self.publish_history:
            log.info(
                'history publish - disabled - '
                '{} - tickers={}'.format(
                    self.name,
                    self.tickers))
            return status
        # end of screening for returning early

        output_record = self.create_history_dataset()

        if output_file or s3_enabled or redis_enabled or slack_enabled:
            log.info(
                'history build json - {} - tickers={}'.format(
                    self.name,
                    self.tickers))
            use_data = json.dumps(output_record)
            num_bytes = len(use_data)
            num_mb = ae_consts.get_mb(num_bytes)
            log.info(
                'history publish - START - '
                '{} - tickers={} '
                'file={} size={}MB '
                's3={} s3_key={} '
                'redis={} redis_key={} '
                'slack={}'.format(
                    self.name,
                    self.tickers,
                    output_file,
                    num_mb,
                    s3_enabled,
                    s3_key,
                    redis_enabled,
                    redis_key,
                    slack_enabled))
            publish_status = publish.publish(
                data=use_data,
                label=label,
                convert_to_json=convert_to_json,
                output_file=output_file,
                compress=compress,
                redis_enabled=redis_enabled,
                redis_key=redis_key,
                redis_address=redis_address,
                redis_db=redis_db,
                redis_password=redis_password,
                redis_expire=redis_expire,
                redis_serializer=redis_serializer,
                redis_encoding=redis_encoding,
                s3_enabled=s3_enabled,
                s3_key=s3_key,
                s3_address=s3_address,
                s3_bucket=s3_bucket,
                s3_access_key=s3_access_key,
                s3_secret_key=s3_secret_key,
                s3_region_name=s3_region_name,
                s3_secure=s3_secure,
                slack_enabled=slack_enabled,
                slack_code_block=slack_code_block,
                slack_full_width=slack_full_width,
                verbose=verbose)

            status = publish_status

            log.info(
                'history publish - END - {} '
                '{} - tickers={} '
                'file={} s3={} redis={} size={}MB'.format(
                    ae_consts.get_status(status=status),
                    self.name,
                    self.tickers,
                    output_file,
                    s3_key,
                    redis_key,
                    num_mb))
        # end of handling for publish

        return status
    # end of publish_trade_history_dataset

    def create_history_dataset(
            self):
        """create_history_dataset

        Create the ``Trading History`` dataset
        during the ``self.publish_trade_history_dataset()`` member method.
        Inherited Algorithm classes can derive how they build a
        custom ``Trading History`` dataset before publishing
        by implementing this method in the derived class.
        """

        log.info('history - create start')

        data_for_tickers = self.get_supported_tickers_in_data(
            data=self.last_handle_data)

        num_tickers = len(data_for_tickers)
        if num_tickers > 0:
            self.debug_msg = (
                '{} handle - tickers={}'.format(
                    self.name,
                    json.dumps(data_for_tickers)))

        output_record = {}
        for ticker in data_for_tickers:
            if ticker not in output_record:
                output_record[ticker] = []
            num_ticker_datasets = len(self.last_handle_data[ticker])
            cur_idx = 1
            for idx, node in enumerate(self.last_handle_data[ticker]):
                track_label = self.build_progress_label(
                    progress=cur_idx,
                    total=num_ticker_datasets)
                algo_id = 'ticker={} {}'.format(
                    ticker,
                    track_label)
                log.info(
                    '{} convert - {} - ds={}'.format(
                        self.name,
                        algo_id,
                        node['date']))

                new_node = {
                    'id': node['id'],
                    'date': node['date'],
                    'data': {}
                }

                # parse the dataset node and set member variables
                self.debug_msg = (
                    '{} START - convert load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))
                self.load_from_dataset(
                    ds_data=node)
                for ds_key in node['data']:
                    empty_ds = self.empty_pd_str
                    data_val = node['data'][ds_key]
                    if ds_key not in new_node['data']:
                        new_node['data'][ds_key] = empty_ds
                    self.debug_msg = (
                        'convert node={} ds_key={}'.format(
                            node,
                            ds_key))
                    if hasattr(data_val, 'to_json'):
                        new_node['data'][ds_key] = data_val.to_json(
                            orient='records',
                            date_format='iso')
                    else:
                        if not data_val:
                            new_node['data'][ds_key] = empty_ds
                        else:
                            new_node['data'][ds_key] = json.dumps(
                                data_val)
                    # if/else
                # for all dataset values in data
                self.debug_msg = (
                    '{} END - convert load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))

                output_record[ticker].append(new_node)
                cur_idx += 1
            # end for all self.last_handle_data[ticker]
        # end of converting dataset

        return output_record
    # end of create_history_dataset

    def publish_input_dataset(
            self,
            **kwargs):
        """publish_input_dataset

        publish input datasets to caches (redis), archives
        (minio s3), a local file (``output_file``) and slack

        :param kwargs: keyword argument dictionary
        :return: tuple: ``status``, ``output_file``
        """

        # parse optional input args
        output_file = kwargs.get(
            'output_file', None)
        label = kwargs.get(
            'label', self.name)
        convert_to_json = kwargs.get(
            'convert_to_json', self.extract_convert_to_json)
        compress = kwargs.get(
            'compress', self.extract_compress)
        redis_enabled = kwargs.get(
            'redis_enabled', False)
        redis_address = kwargs.get(
            'redis_address', self.extract_redis_address)
        redis_db = kwargs.get(
            'redis_db', self.extract_redis_db)
        redis_password = kwargs.get(
            'redis_password', self.extract_redis_password)
        redis_expire = kwargs.get(
            'redis_expire', self.extract_redis_expire)
        redis_serializer = kwargs.get(
            'redis_serializer', self.extract_redis_serializer)
        redis_encoding = kwargs.get(
            'redis_encoding', self.extract_redis_encoding)
        s3_enabled = kwargs.get(
            's3_enabled', False)
        s3_address = kwargs.get(
            's3_address', self.extract_s3_address)
        s3_bucket = kwargs.get(
            's3_bucket', self.extract_s3_bucket)
        s3_access_key = kwargs.get(
            's3_access_key', self.extract_s3_access_key)
        s3_secret_key = kwargs.get(
            's3_secret_key', self.extract_s3_secret_key)
        s3_region_name = kwargs.get(
            's3_region_name', self.extract_s3_region_name)
        s3_secure = kwargs.get(
            's3_secure', self.extract_s3_secure)
        slack_enabled = kwargs.get(
            'slack_enabled', self.extract_slack_enabled)
        slack_code_block = kwargs.get(
            'slack_code_block', self.extract_slack_code_block)
        slack_full_width = kwargs.get(
            'slack_full_width', self.extract_slack_full_width)
        redis_key = kwargs.get(
            'redis_key', self.extract_redis_key)
        s3_key = kwargs.get(
            's3_key', self.extract_s3_key)
        verbose = kwargs.get(
            'verbose', self.extract_verbose)

        status = ae_consts.NOT_RUN

        if not self.publish_input:
            log.info(
                'input publish - disabled - '
                '{} - tickers={}'.format(
                    self.name,
                    self.tickers))
            return status

        output_record = self.create_algorithm_ready_dataset()

        if output_file or s3_enabled or redis_enabled or slack_enabled:
            log.info(
                'input build json - {} - tickers={}'.format(
                    self.name,
                    self.tickers))
            use_data = json.dumps(output_record)
            num_bytes = len(use_data)
            num_mb = ae_consts.get_mb(num_bytes)
            log.info(
                'input publish - START - '
                '{} - tickers={} '
                'file={} size={}MB '
                's3={} s3_key={} '
                'redis={} redis_key={} '
                'slack={}'.format(
                    self.name,
                    self.tickers,
                    output_file,
                    num_mb,
                    s3_enabled,
                    s3_key,
                    redis_enabled,
                    redis_key,
                    slack_enabled))
            publish_status = publish.publish(
                data=use_data,
                label=label,
                convert_to_json=convert_to_json,
                output_file=output_file,
                compress=compress,
                redis_enabled=redis_enabled,
                redis_key=redis_key,
                redis_address=redis_address,
                redis_db=redis_db,
                redis_password=redis_password,
                redis_expire=redis_expire,
                redis_serializer=redis_serializer,
                redis_encoding=redis_encoding,
                s3_enabled=s3_enabled,
                s3_key=s3_key,
                s3_address=s3_address,
                s3_bucket=s3_bucket,
                s3_access_key=s3_access_key,
                s3_secret_key=s3_secret_key,
                s3_region_name=s3_region_name,
                s3_secure=s3_secure,
                slack_enabled=slack_enabled,
                slack_code_block=slack_code_block,
                slack_full_width=slack_full_width,
                verbose=verbose)

            status = publish_status

            log.info(
                'input publish - END - {} '
                '{} - tickers={} '
                'file={} s3={} redis={} size={}MB'.format(
                    ae_consts.get_status(status=status),
                    self.name,
                    self.tickers,
                    output_file,
                    s3_key,
                    redis_key,
                    num_mb))
        # end of handling for publish

        return status
    # end of publish_input_dataset

    def create_algorithm_ready_dataset(
            self):
        """create_algorithm_ready_dataset

        Create the ``Algorithm-Ready`` dataset
        during the ``self.publish_input_dataset()`` member method.
        Inherited Algorithm classes can derive how they build a
        custom ``Algorithm-Ready`` dataset before publishing
        by implementing this method in the derived class.
        """

        log.info('algo-ready - create start')

        data_for_tickers = self.get_supported_tickers_in_data(
            data=self.last_handle_data)

        num_tickers = len(data_for_tickers)
        if num_tickers > 0:
            self.debug_msg = (
                '{} handle - tickers={}'.format(
                    self.name,
                    json.dumps(data_for_tickers)))

        output_record = {}
        for ticker in data_for_tickers:
            if ticker not in output_record:
                output_record[ticker] = []
            num_ticker_datasets = len(self.last_handle_data[ticker])
            cur_idx = 1
            for idx, node in enumerate(self.last_handle_data[ticker]):
                track_label = self.build_progress_label(
                    progress=cur_idx,
                    total=num_ticker_datasets)
                algo_id = 'ticker={} {}'.format(
                    ticker,
                    track_label)
                log.info(
                    '{} convert - {} - ds={}'.format(
                        self.name,
                        algo_id,
                        node['date']))

                new_node = {
                    'id': node['id'],
                    'date': node['date'],
                    'data': {}
                }

                # parse the dataset node and set member variables
                self.debug_msg = (
                    '{} START - convert load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))
                self.load_from_dataset(
                    ds_data=node)
                for ds_key in node['data']:
                    empty_ds = self.empty_pd_str
                    data_val = node['data'][ds_key]
                    if ds_key not in new_node['data']:
                        new_node['data'][ds_key] = empty_ds
                    self.debug_msg = (
                        'convert node={} ds_key={}'.format(
                            node,
                            ds_key))
                    if hasattr(data_val, 'to_json'):
                        new_node['data'][ds_key] = data_val.to_json(
                            orient='records',
                            date_format='iso')
                    else:
                        if not data_val:
                            new_node['data'][ds_key] = empty_ds
                        else:
                            new_node['data'][ds_key] = json.dumps(
                                data_val)
                    # if/else
                # for all dataset values in data
                self.debug_msg = (
                    '{} END - convert load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))

                output_record[ticker].append(new_node)
                cur_idx += 1
            # end for all self.last_handle_data[ticker]
        # end of converting dataset

        return output_record
    # end of create_algorithm_ready_dataset

    def get_ticker_positions(
            self,
            ticker):
        """get_ticker_positions

        get the current positions for a ticker and
        returns a tuple:
        ``num_owned (integer), buys (list), sells (list)```

        .. code-block:: python

            num_owned, buys, sells = self.get_ticker_positions(
                ticker=ticker)

        :param ticker: ticker to lookup
        """
        buys = None
        sells = None
        num_owned = None
        if ticker in self.positions:
            num_owned = self.positions[ticker].get(
                'shares',
                None)
            buys = self.positions[ticker].get(
                'buys',
                [])
            sells = self.positions[ticker].get(
                'sells',
                [])
        return num_owned, buys, sells
    # end of get_ticker_positions

    def get_trade_history_node(
                self):
        """get_trade_history_node

            Helper for quickly building a history node
            on a derived algorithm. Whatever member variables
            are in the base class ``analysis_engine.algo.BaseAlgo``
            will be added automatically into the returned:
            ``historical transaction dictionary``

            .. tip:: if you get a ``None`` back it means there
                could be a bug in how you are using the member
                variables (likely created an invalid math
                calculation) or could be a bug in the helper:
                `build_trade_history_entry <https://github.c
                om/AlgoTraders/stock-analysis-engine/blob/ma
                ster/analysis_engine/build_trade_history_entry.py>`__
        """
        history_dict = history_utils.build_trade_history_entry(
            ticker=self.ticker,
            algo_start_price=self.starting_close,
            original_balance=self.starting_balance,
            num_owned=self.num_owned,
            close=self.trade_price,
            balance=self.balance,
            commission=self.commission,
            date=self.trade_date,
            trade_type=self.trade_type,
            high=self.latest_high,
            low=self.latest_low,
            open_val=self.latest_open,
            volume=self.latest_volume,
            today_high=self.today_high,
            today_low=self.today_low,
            today_open_val=self.today_open,
            today_close=self.today_close,
            today_volume=self.today_volume,
            ask=self.ask,
            bid=self.bid,
            stop_loss=self.stop_loss,
            trailing_stop_loss=self.trailing_stop_loss,
            buy_hold_units=self.buy_hold_units,
            sell_hold_units=self.sell_hold_units,
            spread_exp_date=self.spread_exp_date,
            prev_balance=self.prev_bal,
            prev_num_owned=self.prev_num_owned,
            total_buys=self.num_buys,
            total_sells=self.num_sells,
            buy_triggered=self.should_buy,
            buy_strength=self.buy_strength,
            buy_risk=self.buy_risk,
            sell_triggered=self.should_sell,
            sell_strength=self.sell_strength,
            sell_risk=self.sell_risk,
            note=self.note,
            ds_id=self.ds_id,
            version=self.version)
        return history_dict
    # end of get_trade_history_node

    def load_from_config(
            self,
            config_dict):
        """load_from_config

        support for replaying algorithms from a trading history

        :param config_dict: algorithm configuration values
            usually from a previous trading history or for
            quickly testing dataset theories in a development
            environment
        """
        if config_dict:
            for k in config_dict:
                if k in self.__dict__:
                    self.__dict__[k] = config_dict[k]
        # end of loading config
    # end of load_from_config

    def get_name(self):
        """get_name"""
        return self.name
    # end of get_name

    def get_result(self):
        """get_result"""

        self.debug_msg = (
            'building results')
        finished_date = ae_utils.utc_now_str()
        self.result = {
            'name': self.name,
            'created': self.created_date,
            'updated': finished_date,
            'open_positions': self.positions,
            'buys': self.get_buys(),
            'sells': self.get_sells(),
            'num_processed': len(self.order_history),
            'history': self.order_history,
            'balance': self.balance,
            'commission': self.commission
        }

        return self.result
    # end of get_result

    def get_debug_msg(
            self):
        """get_debug_msg

        debug algorithms that failed
        by viewing the last ``self.debug_msg`` they
        set
        """
        return self.debug_msg
    # end of get_debug_msg

    def get_balance(
            self):
        """get_balance"""
        return self.balance
    # end of get_balance

    def get_buys(
            self):
        """get_buys"""
        return self.buys
    # end of get_buys

    def get_sells(
            self):
        """get_sells"""
        return self.sells
    # end of get_sells

    def get_owned_shares(
            self,
            ticker):
        """get_owned_shares

        :param ticker: ticker to lookup
        """
        num_owned = 0
        if ticker in self.positions:
            num_owned = self.positions[ticker].get(
                'shares',
                None)
        return num_owned
    # end of get_owned_shares

    def create_buy_order(
            self,
            ticker,
            row,
            shares=None,
            reason=None,
            orient='records',
            date_format='iso'):
        """create_buy_order

        create a buy order at the close or ask price

        :param ticker: string ticker
        :param shares: optional - integer number of shares to buy
            if None buy max number of shares at the ``close`` with the
            available ``balance`` amount.
        :param row: ``dictionary`` or ``pd.DataFrame``
            row record that will be converted to a
            json-serialized string
        :param reason: optional - reason for creating the order
            which is useful for troubleshooting order histories
        :param orient: optional - pandas orient for ``row.to_json()``
        :param date_format: optional - pandas date_format
            parameter for ``row.to_json()``
        """
        close = row['close']
        dataset_date = row['date']
        log.info(
            '{} - buy start {}@{} - shares={}'.format(
                self.name,
                ticker,
                close,
                shares))
        new_buy = None

        order_details = row
        if hasattr(row, 'to_json'):
            order_details = row.to_json(
                orient='records',
                date_format='iso'),
        try:
            num_owned = self.get_owned_shares(
                ticker=ticker)
            new_buy = buy_utils.build_buy_order(
                ticker=ticker,
                close=close,
                num_owned=num_owned,
                shares=shares,
                balance=self.balance,
                commission=self.commission,
                date=dataset_date,
                use_key='{}_{}'.format(
                    ticker,
                    dataset_date),
                details=order_details,
                reason=reason)

            prev_shares = num_owned
            if not prev_shares:
                prev_shares = 0
            prev_bal = self.balance
            if new_buy['status'] == ae_consts.TRADE_FILLED:
                if ticker in self.positions:
                    self.positions[ticker]['shares'] += int(
                        new_buy['shares'])
                    self.positions[ticker]['buys'].append(
                        new_buy)
                    (self.num_owned,
                     self.num_buys,
                     self.num_sells) = self.get_ticker_positions(
                        ticker=ticker)
                    self.created_buy = True
                else:
                    self.positions[ticker] = {
                        'shares': new_buy['shares'],
                        'buys': [
                            new_buy
                        ],
                        'sells': []
                    }
                self.balance = new_buy['balance']
                log.info(
                    '{} - buy end {}@{} {} shares={} cost={} bal={} '
                    'prev_shares={} prev_bal={}'.format(
                        self.name,
                        ticker,
                        close,
                        ae_consts.get_status(status=new_buy['status']),
                        new_buy['shares'],
                        new_buy['buy_price'],
                        self.balance,
                        prev_shares,
                        prev_bal))
            else:
                log.error(
                    '{} - buy failed {}@{} {} shares={} cost={} '
                    'bal={} '.format(
                        self.name,
                        ticker,
                        close,
                        ae_consts.get_status(status=new_buy['status']),
                        num_owned,
                        new_buy['buy_price'],
                        self.balance))
            # end of if trade worked or not

            self.buys.append(new_buy)
        except Exception as e:
            self.debug_msg = (
                '{} - buy {}@{} - FAILED with ex={}'.format(
                    self.name,
                    ticker,
                    close,
                    e))
            log.error(self.debug_msg)
            if self.raise_on_err:
                raise e
        # end of try/ex

        (self.num_owned,
         self.num_buys,
         self.num_sells) = self.get_ticker_positions(
            ticker=ticker)

    # end of create_buy_order

    def create_sell_order(
            self,
            ticker,
            row,
            shares=None,
            reason=None,
            orient='records',
            date_format='iso'):
        """create_sell_order

        create a sell order at the close or ask price

        :param ticker: string ticker
        :param shares: optional - integer number of shares to sell
            if None sell all owned shares at the ``close``
        :param row: ``pd.DataFrame`` row record that will
            be converted to a json-serialized string
        :param reason: optional - reason for creating the order
            which is useful for troubleshooting order histories
        :param orient: optional - pandas orient for ``row.to_json()``
        :param date_format: optional - pandas date_format
            parameter for ``row.to_json()``
        """
        close = row['close']
        dataset_date = row['date']
        log.info(
            '{} - sell start {}@{}'.format(
                self.name,
                ticker,
                close))
        new_sell = None
        order_details = row
        if hasattr(row, 'to_json'):
            order_details = row.to_json(
                orient=orient,
                date_format=date_format),
        try:
            num_owned = self.get_owned_shares(
                ticker=ticker)
            new_sell = sell_utils.build_sell_order(
                ticker=ticker,
                close=close,
                num_owned=num_owned,
                shares=shares,
                balance=self.balance,
                commission=self.commission,
                date=dataset_date,
                use_key='{}_{}'.format(
                    ticker,
                    dataset_date),
                details=order_details,
                reason=reason)

            prev_shares = num_owned
            if not prev_shares:
                prev_shares = 0
            prev_bal = self.balance
            if new_sell['status'] == ae_consts.TRADE_FILLED:
                if ticker in self.positions:
                    self.positions[ticker]['shares'] += int(
                        new_sell['shares'])
                    self.positions[ticker]['sells'].append(
                        new_sell)
                    (self.num_owned,
                     self.num_buys,
                     self.num_sells) = self.get_ticker_positions(
                        ticker=ticker)
                    self.created_sell = True
                else:
                    self.positions[ticker] = {
                        'shares': new_sell['shares'],
                        'buys': [],
                        'sells': [
                            new_sell
                        ]
                    }
                self.balance = new_sell['balance']
                log.info(
                    '{} - sell end {}@{} {} shares={} cost={} bal={} '
                    'prev_shares={} prev_bal={}'.format(
                        self.name,
                        ticker,
                        close,
                        ae_consts.get_status(status=new_sell['status']),
                        num_owned,
                        new_sell['sell_price'],
                        self.balance,
                        prev_shares,
                        prev_bal))
            else:
                log.error(
                    '{} - sell failed {}@{} {} shares={} cost={} '
                    'bal={} '.format(
                        self.name,
                        ticker,
                        close,
                        ae_consts.get_status(status=new_sell['status']),
                        num_owned,
                        new_sell['sell_price'],
                        self.balance))
            # end of if trade worked or not

            self.sells.append(new_sell)
        except Exception as e:
            self.debug_msg = (
                '{} - sell {}@{} - FAILED with ex={}'.format(
                    self.name,
                    ticker,
                    close,
                    e))
            log.error(self.debug_msg)
            if self.raise_on_err:
                raise e
        # end of try/ex

        (self.num_owned,
         self.num_buys,
         self.num_sells) = self.get_ticker_positions(
            ticker=ticker)

    # end of create_sell_order

    def build_progress_label(
            self,
            progress,
            total):
        """build_progress_label

        create a progress label string for the logs

        :param progress: progress counter
        :param total: total number of counts
        """
        percent_done = ae_consts.get_percent_done(
            progress=progress,
            total=total)
        progress_label = '{} {}/{}'.format(
            percent_done,
            progress,
            total)
        return progress_label
    # end of build_progress_label

    def get_supported_tickers_in_data(
            self,
            data):
        """get_supported_tickers_in_data

        For all updates found in ``data`` compare to the
        supported list of ``self.tickers`` to make sure
        the updates are relevant for this algorithm.

        :param data: new data stream to process in this
            algo
        """
        data_for_tickers = []
        for ticker in self.tickers:
            if ticker in data:
                data_for_tickers.append(
                    ticker)
        # end of finding tickers for this algo

        return data_for_tickers
    # end of get_supported_tickers_in_data

    def load_from_dataset(
            self,
            ds_data):
        """load_from_dataset

        Load the member variables from the extracted
        ``ds_data`` dataset.

        algorithms automatically provide the following
        member variables to  ``myalgo.process()`` for
        quickly building algorithms:

        - ``self.df_daily``
        - ``self.df_minute``
        - ``self.df_calls``
        - ``self.df_puts``
        - ``self.df_quote``
        - ``self.df_pricing``
        - ``self.df_stats``
        - ``self.df_peers``
        - ``self.df_iex_news``
        - ``self.df_financials``
        - ``self.df_earnings``
        - ``self.df_dividends``
        - ``self.df_company``
        - ``self.df_yahoo_news``

        .. note:: If a key is not in the dataset, the
            algorithms's member variable will be an empty
            ``pd.DataFrame([])``. Please ensure the engine
            cached the dataset in redis using a tool like
            ``redis-cli`` to verify the values are in
            memory.

        :param ds_data: extracted, structured
            dataset from redis
        """

        # back up for debugging/tracking/comparing
        self.last_ds_id = self.ds_id
        self.last_ds_date = self.ds_date
        self.last_ds_data = self.ds_data

        # load the new one
        self.ds_data = ds_data

        self.ds_id = self.ds_data.get(
            'id',
            'missing-ID')
        self.ds_date = self.ds_data.get(
            'date',
            'missing-DATE')
        self.ds_data = self.ds_data.get(
            'data',
            'missing-DATA')
        self.df_daily = self.ds_data.get(
            'daily',
            self.empty_pd)
        self.df_minute = self.ds_data.get(
            'minute',
            self.empty_pd)
        self.df_stats = self.ds_data.get(
            'stats',
            self.empty_pd)
        self.df_peers = self.ds_data.get(
            'peers',
            self.empty_pd)
        self.df_financials = self.ds_data.get(
            'financials',
            self.empty_pd)
        self.df_earnings = self.ds_data.get(
            'earnings',
            self.empty_pd)
        self.df_dividends = self.ds_data.get(
            'dividends',
            self.empty_pd)
        self.df_quote = self.ds_data.get(
            'quote',
            self.empty_pd)
        self.df_company = self.ds_data.get(
            'company',
            self.empty_pd)
        self.df_iex_news = self.ds_data.get(
            'news1',
            self.empty_pd)
        self.df_yahoo_news = self.ds_data.get(
            'news',
            self.empty_pd)
        self.df_calls = self.ds_data.get(
            'calls',
            self.empty_pd)
        self.df_puts = self.ds_data.get(
            'puts',
            self.empty_pd)
        self.df_pricing = self.ds_data.get(
            'pricing',
            {})

        self.latest_min = None
        self.backtest_date = self.ds_date

        if not hasattr(self.df_daily, 'index'):
            self.df_daily = self.empty_pd
        if not hasattr(self.df_minute, 'index'):
            self.df_minute = self.empty_pd
        else:
            if 'date' in self.df_minute:
                self.latest_min = self.df_minute['date'].iloc[-1]
        if not hasattr(self.df_stats, 'index'):
            self.df_stats = self.empty_pd
        if not hasattr(self.df_peers, 'index'):
            self.df_peers = self.empty_pd
        if not hasattr(self.df_financials, 'index'):
            self.df_financials = self.empty_pd
        if not hasattr(self.df_earnings, 'index'):
            self.df_earnings = self.empty_pd
        if not hasattr(self.df_dividends, 'index'):
            self.df_dividends = self.empty_pd
        if not hasattr(self.df_quote, 'index'):
            self.df_quote = self.empty_pd
        if not hasattr(self.df_company, 'index'):
            self.df_company = self.empty_pd
        if not hasattr(self.df_iex_news, 'index'):
            self.df_iex_news = self.empty_pd
        if not hasattr(self.df_yahoo_news, 'index'):
            self.df_yahoo_news = self.empty_pd
        if not hasattr(self.df_calls, 'index'):
            self.df_calls = self.empty_pd
        if not hasattr(self.df_puts, 'index'):
            self.df_puts = self.empty_pd
        if not hasattr(self.df_pricing, 'index'):
            self.df_pricing = self.empty_pd

        # set internal values:
        self.trade_date = self.ds_date
        self.created_buy = False
        self.created_sell = False
        self.should_buy = False
        self.should_sell = False

        try:
            if hasattr(self.df_daily, 'index'):
                columns = self.df_daily.columns.values
                if 'high' in columns:
                    self.today_high = float(
                        self.df_daily.iloc[-1]['high'])
                if 'low' in columns:
                    self.today_low = float(
                        self.df_daily.iloc[-1]['low'])
                if 'open' in columns:
                    self.today_open = float(
                        self.df_daily.iloc[-1]['open'])
                if 'close' in columns:
                    self.today_close = float(
                        self.df_daily.iloc[-1]['close'])
                    self.trade_price = self.today_close
                    if not self.starting_close:
                        self.starting_close = self.today_close
                if 'volume' in columns:
                    self.today_volume = int(
                        self.df_daily.iloc[-1]['volume'])
            if hasattr(self.df_minute, 'index'):
                columns = self.df_minute.columns.values
                if 'high' in columns:
                    self.latest_high = float(
                        self.df_minute.iloc[-1]['high'])
                if 'low' in columns:
                    self.latest_low = float(
                        self.df_minute.iloc[-1]['low'])
                if 'open' in columns:
                    self.latest_open = float(
                        self.df_minute.iloc[-1]['open'])
                if 'close' in columns:
                    self.latest_close = float(
                        self.df_minute.iloc[-1]['close'])
                    self.trade_price = self.latest_close
                    if not self.starting_close:
                        self.starting_close = self.latest_close
                if 'volume' in columns:
                    self.latest_volume = int(
                        self.df_minute.iloc[-1]['volume'])
        except Exception as e:
            self.debug_msg = (
                '{} handle - FAILED getting latest prices '
                'for algo={} - ds={} ex={}'.format(
                    self.name,
                    self.ds_id,
                    self.ds_date,
                    e))
            log.error(self.debug_msg)
            if self.raise_on_err:
                raise e
        # end of trying to get the latest prices out of the
        # datasets
    # end of load_from_dataset

    def reset_for_next_run(
            self):
        """reset_for_next_run

        work in progress - clean up all internal member variables
        for another run

        .. note:: random or probablistic predictions may not
            create the same trading history_output_file
        """
        self.debug_msg = ''
        self.loaded_dataset = None
        self.last_history_dict = None
        self.last_handle_data = None
        self.order_history = []
    # end of reset_for_next_run

    def handle_data(
            self,
            data):
        """handle_data

        process new data for the algorithm using a multi-ticker
        mapping structure

        :param data: dictionary of extracted data from
            the redis pipeline with a structure:
            ::

                ticker = 'SPY'
                # string usually: YYYY-MM-DD
                date = '2018-11-05'
                # redis cache key for the dataset format: <ticker>_<date>
                dataset_id = '{}_{}'.format(
                    ticker,
                    date)
                dataset = {
                    ticker: [
                        {
                            'id': dataset_id,
                            'date': date,
                            'data': {
                                'daily': pd.DataFrame([]),
                                'minute': pd.DataFrame([]),
                                'quote': pd.DataFrame([]),
                                'stats': pd.DataFrame([]),
                                'peers': pd.DataFrame([]),
                                'news1': pd.DataFrame([]),
                                'financials': pd.DataFrame([]),
                                'earnings': pd.DataFrame([]),
                                'dividends': pd.DataFrame([]),
                                'calls': pd.DataFrame([]),
                                'puts': pd.DataFrame([]),
                                'pricing': pd.DataFrame([]),
                                'news': pd.DataFrame([])
                            }
                        }
                    ]
                }

        """

        self.debug_msg = (
            '{} handle - start'.format(
                self.name))

        if self.loaded_dataset:
            log.info(
                '{} handle - using existing dataset '
                'file={} s3={} redis={}'.format(
                    self.name,
                    self.dsload_output_file,
                    self.dsload_s3_key,
                    self.dsload_redis_key))
            data = self.loaded_dataset

        data_for_tickers = self.get_supported_tickers_in_data(
            data=data)

        num_tickers = len(data_for_tickers)
        if num_tickers > 0:
            self.debug_msg = (
                '{} handle - tickers={}'.format(
                    self.name,
                    json.dumps(data_for_tickers)))

        for ticker in data_for_tickers:
            num_ticker_datasets = len(data[ticker])
            cur_idx = 1
            for idx, node in enumerate(data[ticker]):
                track_label = self.build_progress_label(
                    progress=cur_idx,
                    total=num_ticker_datasets)
                algo_id = 'ticker={} {}'.format(
                    ticker,
                    track_label)
                log.info(
                    '{} handle - {} - id={} ds={}'.format(
                        self.name,
                        algo_id,
                        node['id'],
                        node['date']))

                self.ticker = ticker
                self.prev_bal = self.balance
                self.prev_num_owned = self.num_owned

                (self.num_owned,
                 self.num_buys,
                 self.num_sells) = self.get_ticker_positions(
                    ticker=ticker)

                # parse the dataset node and set member variables
                self.debug_msg = (
                    '{} START - load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))
                self.load_from_dataset(
                    ds_data=node)
                self.debug_msg = (
                    '{} END - load dataset id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))

                """
                Indicator Processor
                """
                if self.iproc:
                    self.debug_msg = (
                        '{} START - indicator processing'.format(
                            ticker))
                    self.iproc.process(
                        algo_id=algo_id,
                        ticker=self.ticker,
                        dataset=node)
                    self.debug_msg = (
                        '{} END - indicator processing'.format(
                            ticker))
                # end of indicator processing

                # thinking this could be a separate celery task
                # to increase horizontal scaling to crunch
                # datasets faster like:
                # http://jsatt.com/blog/class-based-celery-tasks/
                self.debug_msg = (
                    '{} START - process id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))
                self.process(
                    algo_id=algo_id,
                    ticker=self.ticker,
                    dataset=node)
                self.debug_msg = (
                    '{} END - process id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))

                # always record the trade history for
                # analysis/review using: myalgo.get_result()
                self.debug_msg = (
                    '{} START - history id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))
                self.last_history_dict = self.get_trade_history_node()
                if self.last_history_dict:
                    self.order_history.append(self.last_history_dict)
                self.debug_msg = (
                    '{} END - history id={}'.format(
                        ticker,
                        node.get('id', 'missing-id')))

                cur_idx += 1
        # for all supported tickers

        # store the last handle dataset
        self.last_handle_data = data

        self.debug_msg = (
            '{} handle - end tickers={}'.format(
                self.name,
                num_tickers))

    # end of handle_data

# end of BaseAlgo
