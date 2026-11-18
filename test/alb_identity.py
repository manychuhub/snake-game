"""Verify identity assertions signed by the deployment's ALB."""

import base64
from functools import lru_cache
import json
import re
import time
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


@lru_cache(maxsize=8)
def signing_key(region, key_id):
    url = f"https://public-keys.auth.elb.{region}.amazonaws.com/{key_id}"
    with urllib.request.urlopen(url, timeout=4) as response:
        return serialization.load_pem_public_key(response.read(4096))


def decode(segment):
    return base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))


def verified_subject(token, expected_signer):
    try:
        header, payload, signature = token.split('.')
        fields = json.loads(decode(header))
        region = expected_signer.split(':')[3]
        key_id = fields['kid']
        if (fields['alg'] != 'ES256' or fields['signer'] != expected_signer
                or int(fields['exp']) <= time.time()
                or not re.fullmatch(r'[a-z]{2}(?:-[a-z]+)+-[0-9]+', region)
                or not re.fullmatch(r'[0-9a-fA-F-]{36}', key_id)):
            return None
        raw = decode(signature)
        if len(raw) != 64:
            return None
        key = signing_key(region, key_id)
        encoded = utils.encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        key.verify(encoded, f'{header}.{payload}'.encode('ascii'), ec.ECDSA(hashes.SHA256()))
        subject = json.loads(decode(payload)).get('sub')
        if isinstance(subject, str) and 0 < len(subject) <= 128:
            return subject
    except (InvalidSignature, ValueError, KeyError, IndexError, TypeError, AttributeError, OSError, OverflowError):
        return None
    return None
