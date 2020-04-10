import logging
import sys
from os import environ

import boto3
import botocore
import click
import dotenv
from tqdm import tqdm

from invest_heat_islands import settings


@click.command()
@click.argument('file_key')
@click.argument('output_filepath', type=click.Path())
def main(file_key, output_filepath):
    logger = logging.getLogger(__name__)

    # callback to display a tqdm progress bar for file downloads
    def hook(t):
        def inner(bytes_amount):
            t.update(bytes_amount)

        return inner

    session = boto3.Session(profile_name=environ.get('S3_PROFILE_NAME'))
    client = session.client(
        's3',
        # if using DigitalOcean Spaces instead of AWS S3
        endpoint_url=environ.get('S3_ENDPOINT_URL'),
    )
    BUCKET_NAME = environ.get('S3_BUCKET_NAME')

    try:
        logger.info("downloading key %s from %s", file_key, BUCKET_NAME)
        filesize = client.head_object(Bucket=BUCKET_NAME,
                                      Key=file_key)['ContentLength']
        with tqdm(total=filesize, unit='B', unit_scale=True,
                  desc=file_key) as t:
            client.download_file(BUCKET_NAME,
                                 file_key,
                                 output_filepath,
                                 Callback=hook(t))
            logger.info("file %s successfully downloaded to %s", file_key,
                        output_filepath)
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            logger.exception("the object %s does not exist", file_key)
            sys.exit(1)
        else:
            raise
    except botocore.exceptions.IncompleteReadError as e:
        logger.exception(e)
        sys.exit(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    dotenv.load_dotenv(dotenv.find_dotenv())

    main()
