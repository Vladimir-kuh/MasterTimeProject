# booking_api/serializers.py

from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta
from .models import Service, Appointment, Client, Employee


# --- НОВЫЙ СЕРИАЛИЗАТОР: Для представления мастеров ---
class EmployeeSerializer(serializers.ModelSerializer):
    """
    Сериализатор для представления Сотрудника/Мастера.
    Используется в EmployeeViewSet.
    """

    class Meta:
        model = Employee
        fields = ('id', 'name')  # Боту нужны только ID и NAME для кнопок


# --- 1. Сериализатор для услуг (с мастерами) ---
class ServiceSerializer(serializers.ModelSerializer):
    """
    Сериализатор для услуг. Добавлено поле 'employees' для отображения привязанных мастеров.
    """
    # Используем EmployeeSerializer для вложенного отображения мастеров
    employees = EmployeeSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        # Включаем новое поле 'employees'
        fields = ['id', 'organization', 'name', 'duration_minutes', 'price', 'is_active', 'employees']


# --- 2. Сериализатор для создания записей (AppointmentCreateSerializer) ---
class AppointmentSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания новых записей.
    Включает логику валидации пересечений и создания клиента.
    """

    client_name = serializers.CharField(max_length=255, write_only=True)
    client_phone_number = serializers.CharField(max_length=20, write_only=True)

    class Meta:
        model = Appointment
        fields = [
            'organization', 'employee', 'service',
            'start_time', 'client_name', 'client_phone_number'
        ]
        read_only_fields = ['end_time', 'status', 'client']

    # --- КРИТИЧЕСКАЯ ВАЛИДАЦИЯ: Защита от перекрытия слотов ---
    def validate(self, data):
        employee = data.get('employee')
        service = data.get('service')
        start_time = data.get('start_time')

        # --- НОВАЯ КРИТИЧЕСКАЯ ПРОВЕРКА: Наличие мастера ---
        if not employee:
            raise serializers.ValidationError({"employee": "Для создания записи должен быть выбран мастер."})
        # ----------------------------------------------------

        # Проверка на бронирование в прошлом
        if start_time < timezone.now():
            raise serializers.ValidationError({"start_time": "Нельзя бронировать время в прошлом."})

        # 1. Расчет времени окончания
        duration = service.duration_minutes
        end_time = start_time + timedelta(minutes=duration)
        data['end_time'] = end_time

        # 2. Проверка на пересечение
        # Убеждаемся, что мастер выбран, прежде чем искать конфликты
        if employee:
            conflicting_appointments = Appointment.objects.filter(
                employee=employee,
                start_time__lt=end_time,
                end_time__gt=start_time
            )

            # Если это обновление (UPDATE), исключаем текущую запись из проверки
            instance = self.instance
            if instance:
                conflicting_appointments = conflicting_appointments.exclude(pk=instance.pk)

            # 3. Если найдено пересечение, вызываем ошибку
            if conflicting_appointments.exists():
                conflict = conflicting_appointments.first()
                # Используем настройки часового пояса для корректного отображения
                tz = timezone.get_current_timezone()
                conflict_start_time = conflict.start_time.astimezone(tz).strftime('%H:%M')
                conflict_end_time = conflict.end_time.astimezone(tz).strftime('%H:%M')

                raise serializers.ValidationError({
                    "time_slot": f"Слот для мастера {employee.name} занят с {conflict_start_time} по {conflict_end_time}."
                })

        return data

    # --- Логика создания (после успешной валидации) ---
    def create(self, validated_data):
        # 1. Создание/получение клиента
        client_name = validated_data.pop('client_name')
        client_phone_number = validated_data.pop('client_phone_number')

        try:
            client, created = Client.objects.get_or_create(
                phone_number=client_phone_number,
                defaults={'name': client_name}
            )
            validated_data['client'] = client
        except Exception as e:
            raise serializers.ValidationError({"client_error": f"Ошибка создания/поиска клиента: {e}"})

        # end_time уже рассчитан в методе validate
        appointment = Appointment.objects.create(**validated_data)
        return appointment


# --- 3. Сериализатор для детального просмотра записей ---
class AppointmentDetailSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    employee_name = serializers.CharField(source='employee.name', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)

    class Meta:
        model = Appointment
        fields = [
            'id', 'organization', 'organization_name', 'employee', 'employee_name',
            'service', 'service_name', 'client', 'client_name',
            'start_time', 'end_time', 'status'
        ]