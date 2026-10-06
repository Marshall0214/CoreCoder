import unittest
from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, TimedSerializer, TimestampSigner


class ClockSigner(TimestampSigner):
    now = 1000

    def get_timestamp(self):
        return type(self).now


class Target(unittest.TestCase):
    def test_signer_rejects_future_with_metadata(self):
        ClockSigner.now = 1100
        signer = ClockSigner('secret')
        token = signer.sign(b'value')
        ClockSigner.now = 1000
        with self.assertRaises(SignatureExpired) as caught:
            signer.unsign(token, max_age=200)
        self.assertEqual(caught.exception.payload, b'value')
        self.assertEqual(caught.exception.date_signed, datetime.fromtimestamp(1100, timezone.utc))
        self.assertFalse(signer.validate(token, max_age=200))

    def test_serializer_rejects_future(self):
        serializer = TimedSerializer('secret', signer=ClockSigner)
        ClockSigner.now = 1100
        token = serializer.dumps({'value': 1})
        ClockSigner.now = 1000
        with self.assertRaises(SignatureExpired):
            serializer.loads(token, max_age=200)


class Controls(unittest.TestCase):
    def test_boundaries_and_unbounded_future(self):
        signer = ClockSigner('secret')
        ClockSigner.now = 1000
        token = signer.sign(b'value')
        for now in (1000, 1010):
            ClockSigner.now = now
            self.assertEqual(signer.unsign(token, max_age=10), b'value')
        ClockSigner.now = 1011
        with self.assertRaises(SignatureExpired):
            signer.unsign(token, max_age=10)
        ClockSigner.now = 999
        self.assertEqual(signer.unsign(token), b'value')

    def test_roundtrip_timestamp_and_tamper(self):
        ClockSigner.now = 1000
        serializer = TimedSerializer('secret', signer=ClockSigner)
        token = serializer.dumps({'value': 1})
        self.assertEqual(serializer.loads(token, max_age=10, return_timestamp=True),
                         ({'value': 1}, datetime.fromtimestamp(1000, timezone.utc)))
        with self.assertRaises(BadSignature):
            serializer.loads('changed' + token, max_age=10)
