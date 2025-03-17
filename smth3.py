import replicate

import replicate
import os

# Установи API-ключ в переменную окружения
os.environ["REPLICATE_API_TOKEN"] = "r8_TaFGkUSHUTT5nRm6YlFTiW9XxnbYJ6N0ZB0tE"

replicate.api_token = 'r8_TaFGkUSHUTT5nRm6YlFTiW9XxnbYJ6N0ZB0tE'

def get_mistral_answer(question):
    response = replicate.run(
        "meta/meta-llama-3-8b-instruct",  # Пример другой модели
        input={
            "prompt": f"Ты — русскоязычный помощник. Отвечай на русском: {question}",
            "max_length": 200
        }
    )
    return "".join(response)


print(get_mistral_answer("Привет! Расскажи про фудкост в прошлом месяце"))