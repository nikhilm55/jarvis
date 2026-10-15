"""SHA-256 pins for every input fetch.py downloads (and Zenodo's own md5 for the DEMAND archives).

A new input is added by running `fetch.py --trust-new KEY`, which downloads it, checks the host's checksum when there is
one, and prints the line to paste here. Nothing is ever fetched unpinned otherwise.
"""

# fmt: off
SHA256 = {
    "demand:DKITCHEN": "9d68e46d2709847c59580770e2f8aa160607ebff7475788174aa1080332cc845",  # pragma: allowlist secret
    "demand:DLIVING": "2b1726fe06e41551ce2397f2aaf3e4fb692c912d81914b04708df0bbb5252338",  # pragma: allowlist secret
    "demand:OMEETING": "512016cad3a42511a0fb7e3c74d6924e6efde4921a6101361f1306bf90bf2e5a",  # pragma: allowlist secret
    "demand:OOFFICE": "7570c952f621990d0d71b8398107d9a78066254f883a5569abec9c233ffda358",  # pragma: allowlist secret
    "demand:PCAFETER": "89be7194b83cd583c4b12f4bf7c19e9cf0e612b95312e9f4aedc968cd811bcd5",  # pragma: allowlist secret
    "librispeech:dev-clean": "76f87d090650617fca0cac8f88b9416e0ebf80350acb97b343a85fa903728ab3",  # pragma: allowlist secret
    "oww:embedding": "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",  # pragma: allowlist secret
    "oww:melspectrogram": "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",  # pragma: allowlist secret
    "piper:en_GB-aru-medium": "9e74d089a8563f8b2446426d01becb046cd3c3bfbafe1a20fd03a9a79bd82619",  # pragma: allowlist secret
    "piper:en_GB-aru-medium.json": "00529fabf0e79f29a9cb10fda5b60f9b7cf80671faac2b316e13af20e7816d5e",  # pragma: allowlist secret
    "piper:en_GB-vctk-medium": "4e9fc85ab9009385319fc6bae7f55577f8a2d7ee77fd9159a5500eb6531f41e6",  # pragma: allowlist secret
    "piper:en_GB-vctk-medium.json": "7f85e6391ed0f7f46e4abd19345929a16be931a0c9945086f96692dce2087fa8",  # pragma: allowlist secret
    "piper:en_US-joe-medium": "58afce0321b8d9c46d7cdf9c16500cc55a793b4220212dba6b70fb788b3baf06",  # pragma: allowlist secret
    "piper:en_US-joe-medium.json": "3d6d5410b3795cb1950595247ef8f06190719e6fdbfa3a2356d8ec368e1aad33",  # pragma: allowlist secret
    "piper:en_US-libritts_r-medium": "10bb85e071d616fcf4071f369f1799d0491492ab3c5d552ec19fb548fac13195",  # pragma: allowlist secret
    "piper:en_US-libritts_r-medium.json": "b471dc60d2d8335e819c393d196d6fbf792817f40051257b269878505bc9afb3",  # pragma: allowlist secret
    "piper:en_US-ljspeech-medium": "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",  # pragma: allowlist secret
    "piper:en_US-ljspeech-medium.json": "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860",  # pragma: allowlist secret
}

MD5 = {
    "demand:DKITCHEN": "7ffbf52d7f4699f96927846103dc8788",  # pragma: allowlist secret
    "demand:DLIVING": "46741384d9e434a0bd8b3ec1830b6052",  # pragma: allowlist secret
    "demand:OMEETING": "62f7cfe7fe6d30b7d8a215fe37c2dfd2",  # pragma: allowlist secret
    "demand:OOFFICE": "7b61cc2d182d5a654cb9c3101ddd4041",  # pragma: allowlist secret
    "demand:PCAFETER": "99927d148128254141a9417d051510bb",  # pragma: allowlist secret
}
# fmt: on
