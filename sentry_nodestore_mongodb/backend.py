from __future__ import annotations

from datetime import datetime, timedelta
from typing import Mapping

import boto3
from botocore.config import Config
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError, OperationFailure
from sentry.nodestore.base import NodeStorage
from sentry.utils.codecs import Codec, ZstdCodec


class MongoNodeStorage(NodeStorage):

    compression_strategies: Mapping[str, Codec[bytes, bytes]] = {
        "zstd": ZstdCodec(),
    }

    def __init__(
            self,
            # Mongo
            mongo_url="mongodb://admin:secret@localhost:27017",
            db_name="sentry_nodestore",
            collection_name="sentry_nodestore",
            default_ttl_days=None,  # TTL в днях
            compression="zstd",
            # Minio
            read_from_s3=False,
            region_name=None,
            bucket_name=None,
            bucket_path=None,
            endpoint_url=None,
            retry_attempts=3,
            aws_access_key_id=None,
            aws_secret_access_key=None
    ):
        # Parameters init

        self.read_from_s3 = read_from_s3

        # Mongo init
        self.url = mongo_url
        self.db_name = db_name
        self.collection_name = collection_name
        self.mongo_client = MongoClient(mongo_url)
        self.db = self.mongo_client[self.db_name]
        self.collection = self.db[self.collection_name]
        self.default_ttl_days = default_ttl_days
        self.compression = compression

        if self.default_ttl_days:
            try:
                self.collection.create_index(
                    [("created_day", ASCENDING)],
                    expireAfterSeconds=self.default_ttl_days * 24 * 3600,
                    name="created_day_ttl"
                )
            except OperationFailure as e:
                if "already exists with different options" in str(e):
                    self.collection.drop_index("created_day_ttl")
                    self.collection.create_index(
                        [("created_day", ASCENDING)],
                        expireAfterSeconds=self.default_ttl_days * 24 * 3600,
                        name="created_day_ttl"
                    )

        # Minio init
        if self.read_from_s3:

            self.bucket_name = bucket_name
            self.bucket_path = bucket_path
            self.s3_client = boto3.client(
                config=Config(
                    retries={
                        'mode': 'standard',
                        'max_attempts': retry_attempts,
                    }
                ),
                region_name=region_name,
                service_name='s3',
                endpoint_url=endpoint_url,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )

    # Delete
    def delete(self, id) -> None:
        self.collection.delete_one({'_id': id})

    def delete_multi(self, id_list: list[str]) -> None:
        self.collection.delete_many({'_id': {'$in': id_list}})

    # Set
    def _set_bytes(self, id: str, data: bytes, ttl: timedelta | None = None) -> None:
        content_encoding = ''
        if self.compression:
            codec = self.compression_strategies[self.compression]
            compressed_data = codec.encode(data)

            # Check if compression is worth it, otherwise store the data uncompressed
            if len(compressed_data) <= len(data):
                data = compressed_data
                content_encoding = self.compression

        created_dt = datetime.combine(datetime.utcnow().date(), datetime.min.time())
        doc = {
            '_id': id,
            'data': data,
            'content_encoding': content_encoding,
            'created_day': created_dt
        }
        try:
            self.collection.insert_one(doc)
        except DuplicateKeyError:
            self.collection.update_one({'_id': id}, {'$set': doc})

    # Get
    def _get_bytes(self, id: str) -> bytes | None:
        doc = self.collection.find_one({'_id': id})
        if doc:
            data = doc['data']
            codec = self.compression_strategies.get(doc['content_encoding'])
            return codec.decode(data) if codec else data
        if self.read_from_s3:
            return self.__read_from_bucket(id)
        return None

    def _get_bytes_multi(self, ids: list[str]) -> dict[str, bytes | None]:
        """
        Быстрая массовая загрузка документов из MongoDB с учётом сжатия
        и fallback на S3.
        """

        # 1. Получаем все документы из MongoDB
        docs = self.collection.find({'_id': {'$in': ids}})

        result: dict[str, bytes | None] = {}

        # 2. Обрабатываем каждый найденный документ
        for doc in docs:
            data = doc['data']
            codec = self.compression_strategies.get(doc.get('content_encoding'))
            result[doc['_id']] = codec.decode(data) if codec else data

        # 3. Для отсутствующих документов — читаем из S3, если нужно
        if self.read_from_s3:
            missing_ids = [id_ for id_ in ids if id_ not in result]
            for id_ in missing_ids:
                result[id_] = self.__read_from_bucket(id_)

        # 4. Для оставшихся, которых нет в БД и S3 — None
        for id_ in ids:
            if id_ not in result:
                result[id_] = None

        return result

    # Cleanup
    def cleanup(self, cutoff_timestamp: datetime) -> None:
        return None


    def __get_key_for_id(self, id: str) -> str:
        if self.bucket_path is None:
            return id
        return self.bucket_path + '/' + id

    def __read_from_bucket(self, id: str) -> bytes | None:
        try:
            obj = self.s3_client.get_object(
                Key=self.__get_key_for_id(id),
                Bucket=self.bucket_name,
            )

            data = obj.get('Body').read()

            codec = self.compression_strategies.get(obj.get('ContentEncoding'))

            value = codec.decode(data) if codec else data
            try:
                self.s3_client.delete_object(
                    Key=self.__get_key_for_id(id),
                    Bucket=self.bucket_name,
                )
                self._set_bytes(id, value)
            except self.s3_client.exceptions.NoSuchKey:
                None
            return value
        except self.s3_client.exceptions.NoSuchKey:
            return None