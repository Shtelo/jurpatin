from requests import get

from util import get_secret

KEY = get_secret('koreaexim_openapi_key')


def get_exchange_rates() -> dict[str, float]:
    """
    returns exchange rate from krw to the currency
    if 1 USD is exchangable with 1200 KRW, USD -> 1200.0
    """

    link = f'https://www.koreaexim.go.kr/site/program/financial/exchangeJSON?authkey={KEY}&data=AP01'
    request = get(link)
    json = request.json()
    return dict(map(lambda x: (x['cur_unit'], float(x['deal_bas_r'].replace(',', ''))), json))


exchangeable_currencies = [
    'AED', 'AUD', 'BHD', 'BND', 'CAD', 'CHF', 'CNH', 'DKK', 'EUR', 'GBP', 'HKD', 'IDR(100)', 'JPY(100)', 'KRW', 'KWD',
    'MYR', 'NOK', 'NZD', 'SAR', 'SEK', 'SGD', 'THB', 'USD']
