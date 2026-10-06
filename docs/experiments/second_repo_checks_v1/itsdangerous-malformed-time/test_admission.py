import unittest
from datetime import datetime, timezone

from itsdangerous import BadTimeSignature, SignatureExpired, TimedSerializer, TimestampSigner
from itsdangerous.encoding import base64_encode, int_to_bytes


class ClockSigner(TimestampSigner):
    now = 1000

    def get_timestamp(self):
        return type(self).now


def invalid_token(payload, timestamp):
    return payload + b'.' + base64_encode(int_to_bytes(timestamp)) + b'.invalid'


class Target(unittest.TestCase):
    def test_signer_normalizes_out_of_range_date(self):
        signer = ClockSigner('secret')
        token = invalid_token(b'value', 10**14)
        try:
            signer.unsign(token)
        except BadTimeSignature as exc:
            self.assertEqual(exc.payload, b'value')
            self.assertIsNone(exc.date_signed)
        except (ValueError, OSError) as exc:
            self.fail(f'Datetime failure must be BadTimeSignature, got {type(exc).__name__}')
        else:
            self.fail('Invalid signature was accepted')

    def test_serializer_and_unsafe_load(self):
        serializer = TimedSerializer('secret', signer=ClockSigner)
        payload = serializer.dump_payload({'value': 1})
        token = invalid_token(payload, 10**14)
        try:
            with self.assertRaises(BadTimeSignature):
                serializer.loads(token)
            self.assertEqual(serializer.loads_unsafe(token), (False, {'value': 1}))
            self.assertFalse(ClockSigner('secret').validate(token))
        except (ValueError, OSError) as exc:
            self.fail(f'Public loaders must normalize datetime failures: {type(exc).__name__}')


class Controls(unittest.TestCase):
    def test_normal_invalid_timestamp_metadata(self):
        with self.assertRaises(BadTimeSignature) as caught:
            ClockSigner('secret').unsign(invalid_token(b'value', 1000))
        self.assertEqual(caught.exception.payload, b'value')
        self.assertEqual(caught.exception.date_signed, datetime.fromtimestamp(1000, timezone.utc))

    def test_roundtrip_and_expiry(self):
        ClockSigner.now = 1000
        serializer = TimedSerializer('secret', signer=ClockSigner)
        token = serializer.dumps({'value': 1})
        self.assertEqual(serializer.loads(token, max_age=10), {'value': 1})
        ClockSigner.now = 1011
        with self.assertRaises(SignatureExpired):
            serializer.loads(token, max_age=10)
