import os
from google.cloud.translate import TranslationServiceAsyncClient
from typing import List

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.getcwd() + f"/bot/{os.getenv('GOOGLE_PROJECT_CREDS_FILENAME', '')}"

client = TranslationServiceAsyncClient()
parent = f"projects/{os.getenv('GOOGLE_PROJECT_API', '')}/locations/global"


async def translate_single(input_text: str):
    translations = await translate([input_text, ])
    result = translations[0]
    if result.detected_language_code == "en":
        return None, None
    return result.translated_text, result.detected_language_code


async def translate(input_strings: List[str]):
    response = await client.translate_text(
        request={
            "parent": parent,
            "contents": input_strings,
            "mime_type": "text/plain",  # mime types: text/plain, text/html
            "target_language_code": "en-US",
        }
    )
    return response.translations

