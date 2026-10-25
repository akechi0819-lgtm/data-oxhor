from pathlib import Path
import hashlib
import io
import tempfile
import unittest
from unittest.mock import patch
from data_platform.query.evidence import file_ref, resolve_file, EvidenceError


class StreamingEvidenceTests(unittest.TestCase):
    def test_large_identity_uses_bounded_reads_and_preserves_exact_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'business.duckdb';payload=b'a'*(3*1024*1024+17)
            path.write_bytes(payload);expected=hashlib.sha256(payload).hexdigest()
            original=Path.open;reads=[]
            class Bounded(io.BufferedReader):
                def read(self,size=-1):
                    if not 0<size<=1024*1024:raise AssertionError('unbounded identity read')
                    reads.append(size);return super().read(size)
            def opened(p,*args,**kwargs):
                if p==path and args==('rb',):return Bounded(original(p,'rb',buffering=0))
                return original(p,*args,**kwargs)
            with patch.object(Path,'open',opened),patch.object(Path,'read_bytes',side_effect=AssertionError('whole file read forbidden')):
                ref=file_ref(path,root,'application/vnd.duckdb')
                self.assertEqual(resolve_file(root,ref),path)
            self.assertEqual(ref,{'path':'business.duckdb','sha256':expected,'size_bytes':len(payload),'media_type':'application/vnd.duckdb'})
            self.assertGreaterEqual(len(reads),8)
            path.write_bytes(b'b'+payload[1:])
            with self.assertRaises(EvidenceError):resolve_file(root,ref)

    def test_file_mutation_during_streaming_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'evidence.bin';path.write_bytes(b'a'*(2*1024*1024))
            original=Path.open
            class Changed(io.BufferedReader):
                changed=False
                def read(self,size=-1):
                    result=super().read(size)
                    if result and not self.changed:
                        self.changed=True
                        with original(path,'ab') as target:target.write(b'b')
                    return result
            def opened(p,*args,**kwargs):
                if p==path and args==('rb',):return Changed(original(p,'rb',buffering=0))
                return original(p,*args,**kwargs)
            with patch.object(Path,'open',opened),self.assertRaisesRegex(EvidenceError,'changed while hashing'):
                file_ref(path,root,'application/octet-stream')
