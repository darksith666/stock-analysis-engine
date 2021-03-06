"""
Helper for creating a buy order
"""

from analysis_engine.consts import TRADE_OPEN
from analysis_engine.consts import TRADE_NOT_ENOUGH_FUNDS
from analysis_engine.consts import TRADE_FILLED
from analysis_engine.consts import ALGO_BUYS_S3_BUCKET_NAME
from analysis_engine.consts import to_f
from analysis_engine.consts import get_status
from analysis_engine.consts import ppj
from analysis_engine.utils import utc_now_str
from spylunking.log.setup_logging import build_colorized_logger

log = build_colorized_logger(
    name=__name__)


def build_buy_order(
        ticker,
        num_owned,
        close,
        balance,
        commission,
        date,
        details,
        use_key,
        shares=None,
        version=1,
        auto_fill=True,
        reason=None):
    """build_buy_order

    Create an algorithm buy order as a dictionary

    :param ticker: ticker
    :param num_owned: integer current owned
        number of shares for this asset
    :param close: float closing price of the asset
    :param balance: float amount of available capital
    :param commission: float for commission costs
    :param date: string trade date for that row usually
        ``COMMON_DATE_FORMAT`` (``YYYY-MM-DD``)
    :param details: dictionary for full row of values to review
        all buys after the algorithm finishes. (usually ``row.to_json()``)
    :param use_key: string for redis and s3 publishing of the algorithm
        result dictionary as a json-serialized dictionary
    :param shares: optional - integer number of shares to buy
        if None buy max number of shares at the ``close`` with the
        available ``balance`` amount.
    :param version: optional - version tracking integer
    :param auto_fill: optional - bool for not assuming the trade
        filled (default ``True``)
    :param reason: optional - string for recording why the algo
        decided to buy for review after the algorithm finishes
    """
    status = TRADE_OPEN
    s3_bucket_name = ALGO_BUYS_S3_BUCKET_NAME
    s3_key = use_key
    redis_key = use_key
    s3_enabled = True
    redis_enabled = True

    cost_of_trade = None
    new_shares = num_owned
    new_balance = balance
    created_date = None

    tradable_funds = balance - (2.0 * commission)

    if close > 0.1 and tradable_funds > 10.0:
        can_buy_num_shares = shares
        if not can_buy_num_shares:
            can_buy_num_shares = int(tradable_funds / close)
        cost_of_trade = to_f(
            val=(can_buy_num_shares * close) + commission)
        if can_buy_num_shares > 0:
            if cost_of_trade > balance:
                status = TRADE_NOT_ENOUGH_FUNDS
            else:
                created_date = utc_now_str()
                if auto_fill:
                    new_shares = num_owned + can_buy_num_shares
                    new_balance = balance - cost_of_trade
                    status = TRADE_FILLED
                else:
                    new_shares = shares
                    new_balance = balance
        else:
            status = TRADE_NOT_ENOUGH_FUNDS
    else:
        status = TRADE_NOT_ENOUGH_FUNDS

    order_dict = {
        'ticker': ticker,
        'status': status,
        'balance': new_balance,
        'shares': new_shares,
        'buy_price': cost_of_trade,
        'prev_balance': balance,
        'prev_shares': num_owned,
        'close': close,
        'details': details,
        'reason': reason,
        'date': date,
        'created': created_date,
        's3_bucket': s3_bucket_name,
        's3_key': s3_key,
        'redis_key': redis_key,
        's3_enabled': s3_enabled,
        'redis_enabled': redis_enabled,
        'version': version
    }

    log.debug(
        '{} {} buy {} order={}'.format(
            ticker,
            date,
            get_status(status=order_dict['status']),
            ppj(order_dict)))

    return order_dict
# end of build_buy_order
