import hashlib
import hmac
import base64
import uuid
import json
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
import requests
from flask import Blueprint, session, redirect, render_template, request, url_for, jsonify, abort
from db import supabase
import settings_store

payment_bp = Blueprint('payment', __name__)


ECPAY_RATES = {
    'credit': {'rate': 2.75, 'flat': 1},
    'atm':    {'rate': 0,    'flat': 15},
    'cvs':    {'rate': 0,    'flat': 28},
}

LINEPAY_RATE = {'rate': 2.9, 'flat': 0}


def _get_gateway_settings():
    return {
        'gateway': settings_store.get('payment_gateway') or 'none',
        'ecpay_merchant_id': settings_store.get('payment_ecpay_merchant_id') or '',
        'ecpay_hash_key': settings_store.get('payment_ecpay_hash_key') or '',
        'ecpay_hash_iv': settings_store.get('payment_ecpay_hash_iv') or '',
        'ecpay_mode': settings_store.get('payment_ecpay_mode') or 'test',
        'linepay_channel_id': settings_store.get('payment_linepay_channel_id') or '',
        'linepay_channel_secret': settings_store.get('payment_linepay_channel_secret') or '',
        'linepay_mode': settings_store.get('payment_linepay_mode') or 'sandbox',
        'manual_instructions': settings_store.get('payment_manual_instructions') or '',
        'fee_handling': settings_store.get('payment_fee_handling') or 'church',
    }


def _apply_surcharge(fee: int, gateway: str) -> int:
    """Return total amount after surcharge (payer absorbs, using published rates)."""
    if gateway == 'ecpay':
        # Use credit card rate as the worst-case (ALL payment methods selected)
        r = ECPAY_RATES['credit']
        surcharge = fee * r['rate'] / 100 + r['flat']
    elif gateway == 'linepay':
        r = LINEPAY_RATE
        surcharge = fee * r['rate'] / 100 + r['flat']
    else:
        return fee
    return int(fee + surcharge + 0.5)  # round up to int NT$


def _ecpay_checksum(params: dict, hash_key: str, hash_iv: str) -> str:
    sorted_items = sorted(params.items(), key=lambda x: x[0].lower())
    param_str = '&'.join(f'{k}={v}' for k, v in sorted_items)
    raw = f'HashKey={hash_key}&{param_str}&HashIV={hash_iv}'
    encoded = quote(raw, safe='').lower()
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest().upper()


def _linepay_signature(channel_secret: str, uri: str, body: str, nonce: str) -> str:
    message = channel_secret + uri + body + nonce
    sig = hmac.new(channel_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(sig).decode('utf-8')


@payment_bp.route('/events/<event_id>/registrations/<reg_id>/pay')
def initiate_payment(event_id, reg_id):
    if not session.get('user_id'):
        return redirect(url_for('auth.login_page'))

    # Verify registration belongs to user
    reg_result = supabase.table('registrations').select('*').eq('id', reg_id).eq('event_id', event_id).execute()
    if not reg_result.data:
        abort(404)
    reg = reg_result.data[0]
    if reg.get('user_id') != session['user_id']:
        abort(403)
    if reg.get('payment_status') == 'paid':
        return redirect(url_for('event.event_detail', event_id=event_id))

    event_result = supabase.table('events').select('*').eq('id', event_id).execute()
    if not event_result.data:
        abort(404)
    event = event_result.data[0]
    fee = int(event.get('fee') or 0)
    if fee <= 0:
        return redirect(url_for('event.event_detail', event_id=event_id))

    cfg = _get_gateway_settings()
    gateway = cfg['gateway']

    # Apply published surcharge if payer absorbs fees
    charge_fee = fee
    surcharge = 0
    if cfg['fee_handling'] == 'payer' and gateway in ('ecpay', 'linepay'):
        charge_fee = _apply_surcharge(fee, gateway)
        surcharge = charge_fee - fee

    if gateway == 'ecpay':
        return _ecpay_initiate(event, reg, charge_fee, cfg, base_fee=fee, surcharge=surcharge)
    elif gateway == 'linepay':
        return _linepay_initiate(event, reg, charge_fee, cfg, base_fee=fee, surcharge=surcharge)
    elif gateway == 'manual':
        return render_template('payment/manual.html', event=event, reg=reg, fee=fee,
                               instructions=cfg['manual_instructions'])
    else:
        return render_template('payment/unavailable.html', event=event)


def _ecpay_initiate(event, reg, fee, cfg, base_fee=None, surcharge=0):
    merchant_id = cfg['ecpay_merchant_id']
    hash_key = cfg['ecpay_hash_key']
    hash_iv = cfg['ecpay_hash_iv']
    is_test = cfg['ecpay_mode'] == 'test'

    if is_test:
        action_url = 'https://payment-stage.ecpay.com.tw/Cashier/AioCheckout/Index'
    else:
        action_url = 'https://payment.ecpay.com.tw/Cashier/AioCheckout/Index'

    trade_no = f"CMS{reg['id'][:8].replace('-','').upper()}"
    trade_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    item_name = event.get('title', '活動費用')[:180]
    if surcharge:
        item_name += f'（含手續費NT${surcharge}）'

    host = request.host_url.rstrip('/')
    return_url = host + url_for('payment.ecpay_return')
    order_result_url = host + url_for('payment.ecpay_result', event_id=event['id'], reg_id=reg['id'])

    params = {
        'MerchantID': merchant_id,
        'MerchantTradeNo': trade_no,
        'MerchantTradeDate': trade_time,
        'PaymentType': 'aio',
        'TotalAmount': str(fee),
        'TradeDesc': '教會活動報名費用',
        'ItemName': item_name,
        'ReturnURL': return_url,
        'OrderResultURL': order_result_url,
        'ChoosePayment': 'ALL',
        'EncryptType': '1',
    }
    params['CheckMacValue'] = _ecpay_checksum(params, hash_key, hash_iv)

    supabase.table('registrations').update({
        'payment_note': f'ecpay:{trade_no}'
    }).eq('id', reg['id']).execute()

    return render_template('payment/ecpay_form.html', action_url=action_url, params=params)


@payment_bp.route('/payment/ecpay/return', methods=['POST'])
def ecpay_return():
    """ECPay server-to-server callback (background notify)"""
    data = request.form.to_dict()
    cfg = _get_gateway_settings()
    received_mac = data.pop('CheckMacValue', '')
    expected_mac = _ecpay_checksum(data, cfg['ecpay_hash_key'], cfg['ecpay_hash_iv'])

    if received_mac.upper() != expected_mac.upper():
        return '0|Error', 200

    trade_no = data.get('MerchantTradeNo', '')
    rts = data.get('RtnCode', '')
    if rts == '1':
        reg_result = supabase.table('registrations').select('id').like('payment_note', f'ecpay:{trade_no}%').execute()
        if reg_result.data:
            supabase.table('registrations').update({'payment_status': 'paid'}).eq('id', reg_result.data[0]['id']).execute()
    return '1|OK', 200


@payment_bp.route('/payment/ecpay/result/<event_id>/<reg_id>')
def ecpay_result(event_id, reg_id):
    """ECPay redirect back to user after payment"""
    rtn = request.args.get('RtnCode') or request.form.get('RtnCode', '')
    if rtn == '1':
        supabase.table('registrations').update({'payment_status': 'paid'}).eq('id', reg_id).execute()
    return redirect(url_for('event.event_detail', event_id=event_id))


def _linepay_initiate(event, reg, fee, cfg, base_fee=None, surcharge=0):
    channel_id = cfg['linepay_channel_id']
    channel_secret = cfg['linepay_channel_secret']
    is_sandbox = cfg['linepay_mode'] == 'sandbox'

    host = request.host_url.rstrip('/')
    confirm_url = host + url_for('payment.linepay_confirm', event_id=event['id'], reg_id=reg['id'])
    cancel_url = host + url_for('event.event_detail', event_id=event['id'])

    order_id = f"CMS-{reg['id'][:8].upper()}"
    uri = '/v3/payments/request'
    body_dict = {
        'amount': fee,
        'currency': 'TWD',
        'orderId': order_id,
        'packages': [{
            'id': order_id,
            'amount': fee,
            'products': [{'name': event.get('title', '活動費用')[:200], 'quantity': 1, 'price': fee}]
        }],
        'redirectUrls': {
            'confirmUrl': confirm_url,
            'cancelUrl': cancel_url,
        }
    }
    body = json.dumps(body_dict, ensure_ascii=False, separators=(',', ':'))
    nonce = str(uuid.uuid4())
    signature = _linepay_signature(channel_secret, uri, body, nonce)

    api_host = 'https://sandbox-api-pay.line.me' if is_sandbox else 'https://api-pay.line.me'
    try:
        resp = requests.post(api_host + uri,
            headers={
                'Content-Type': 'application/json',
                'X-LINE-ChannelId': channel_id,
                'X-LINE-Authorization-Nonce': nonce,
                'X-LINE-Authorization': signature,
            },
            data=body.encode('utf-8'),
            timeout=10
        )
        result = resp.json()
    except Exception as e:
        return render_template('payment/error.html', error=str(e))

    if result.get('returnCode') == '0000':
        payment_url = result['info']['paymentUrl']['web']
        supabase.table('registrations').update({
            'payment_note': f"linepay:{result['info']['transactionId']}"
        }).eq('id', reg['id']).execute()
        return redirect(payment_url)
    else:
        return render_template('payment/error.html', error=result.get('returnMessage', '付款建立失敗'))


@payment_bp.route('/payment/linepay/confirm/<event_id>/<reg_id>')
def linepay_confirm(event_id, reg_id):
    transaction_id = request.args.get('transactionId')
    cfg = _get_gateway_settings()
    channel_id = cfg['linepay_channel_id']
    channel_secret = cfg['linepay_channel_secret']
    is_sandbox = cfg['linepay_mode'] == 'sandbox'

    reg_result = supabase.table('registrations').select('*').eq('id', reg_id).execute()
    if not reg_result.data:
        abort(404)
    reg = reg_result.data[0]

    event_result = supabase.table('events').select('fee').eq('id', event_id).execute()
    fee = int(event_result.data[0].get('fee', 0)) if event_result.data else 0

    uri = f'/v3/payments/{transaction_id}/confirm'
    body_dict = {'amount': fee, 'currency': 'TWD'}
    body = json.dumps(body_dict, separators=(',', ':'))
    nonce = str(uuid.uuid4())
    signature = _linepay_signature(channel_secret, uri, body, nonce)

    api_host = 'https://sandbox-api-pay.line.me' if is_sandbox else 'https://api-pay.line.me'
    try:
        resp = requests.post(api_host + uri,
            headers={
                'Content-Type': 'application/json',
                'X-LINE-ChannelId': channel_id,
                'X-LINE-Authorization-Nonce': nonce,
                'X-LINE-Authorization': signature,
            },
            data=body.encode('utf-8'),
            timeout=10
        )
        result = resp.json()
    except Exception as e:
        return render_template('payment/error.html', error=str(e))

    if result.get('returnCode') == '0000':
        supabase.table('registrations').update({'payment_status': 'paid'}).eq('id', reg_id).execute()

    return redirect(url_for('event.event_detail', event_id=event_id))
