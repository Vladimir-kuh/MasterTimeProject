# master_time_project/сelery.py

import os
from celery import Celery

# Устанавливаем настройки Django по умолчанию для Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'master_time_project.settings')

# Инициализируем Celery Application. 'MasterTimeProject' - имя вашего проекта
app = Celery('master_time_project')

# Используем настройки Django: все конфигурации Celery должны начинаться с префикса 'CELERY_' в settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

# Автоматически обнаруживать и регистрировать таски (задачи) из всех установленных приложений
app.autodiscover_tasks()

# Опционально: тестовая задача
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
