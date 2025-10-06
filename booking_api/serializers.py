# booking_api/serializers.py (ИСПРАВЛЕННАЯ ВЕРСИЯ)

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
        fields = ('id', 'name')


# --- 1. Сериализатор для услуг (с мастерами) ---
class ServiceSerializer(serializers.ModelSerializer):
    """
    Сериализатор для услуг.
    ИСПРАВЛЕНО: Обновлены имена полей. Добавлено total_duration.
    """
    # Используем EmployeeSerializer для вложенного отображения мастеров
    employees = EmployeeSerializer(many=True, read_only=True)

    # Добавляем свойство total_duration (база + буфер)
    total_duration = serializers.ReadOnlyField()
    # Добавляем свойство actual_price (база + кастом, если есть)
    actual_price = serializers.DecimalField(max_digits=10, decimal_places=2, source='base_price', read_only=True)

    class Meta:
        model = Service
        # Включаем новые поля
        fields = [
            'id',
            'organization',
            'category',
            'name',
            'description',
            'base_duration',
            'buffer_time',
            'total_duration',
            'base_price',
            'actual_price',
            'is_active',
            'employees'
        ]


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
        # Добавьте 'address', если он необходим при создании
        fields = [
            'organization', 'employee', 'service',
            'start_time', 'address', 'client_name', 'client_phone_number'
        ]
        # end_time рассчитывается, status по умолчанию PENDING/CONFIRMED, client создается
        read_only_fields = ['end_time', 'status', 'client']

    # --- КРИТИЧЕСКАЯ ВАЛИДАЦИЯ: Защита от перекрытия слотов ---
    def validate(self, data):
        employee = data.get('employee')
        service = data.get('service')
        start_time = data.get('start_time')

        if not employee:
            raise serializers.ValidationError({"employee": "Для создания записи должен быть выбран мастер."})

        # Проверка на бронирование в прошлом
        if start_time < timezone.now():
            raise serializers.ValidationError({"start_time": "Нельзя бронировать время в прошлом."})

        # 1. Расчет времени окончания
        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем total_duration (база + буфер)
        duration = service.total_duration
        end_time = start_time + timedelta(minutes=duration)
        data['end_time'] = end_time

        # NOTE: base_duration и base_price должны быть сохранены в полях
        # custom_duration и custom_price, чтобы сохранить "снимок" цены и длительности
        # на момент записи. Делаем это в методе create.

        # 2. Проверка на пересечение (логика остаётся верной)
        if employee:
            conflicting_appointments = Appointment.objects.filter(
                employee=employee,
                start_time__lt=end_time,
                end_time__gt=start_time
            )

            instance = self.instance
            if instance:
                conflicting_appointments = conflicting_appointments.exclude(pk=instance.pk)

            if conflicting_appointments.exists():
                conflict = conflicting_appointments.first()
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
        service = validated_data.get('service')

        try:
            client, created = Client.objects.get_or_create(
                phone_number=client_phone_number,
                defaults={'name': client_name}
            )
            validated_data['client'] = client
        except Exception as e:
            raise serializers.ValidationError({"client_error": f"Ошибка создания/поиска клиента: {e}"})

        # 2. Сохранение "снимка" цены и длительности услуги в кастомных полях записи
        # Это нужно, чтобы цена и длительность записи не менялись, если изменится услуга
        validated_data['custom_duration'] = service.base_duration
        validated_data['custom_price'] = service.base_price

        appointment = Appointment.objects.create(**validated_data)
        return appointment


# --- 3. Сериализатор для детального просмотра записей ---
class AppointmentDetailSerializer(serializers.ModelSerializer):
    """
    Сериализатор для детального просмотра и обновления записей.
    Использует @property 'actual_duration' и 'actual_price' из модели.
    """
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    employee_name = serializers.CharField(source='employee.name', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True)

    # Поля, которые возвращают фактическое значение (с учетом кастомных данных)
    actual_duration = serializers.ReadOnlyField()
    actual_price = serializers.ReadOnlyField()

    class Meta:
        model = Appointment
        fields = [
            'id', 'organization', 'organization_name', 'employee', 'employee_name',
            'service', 'service_name', 'client', 'client_name',
            'start_time', 'end_time', 'status', 'address',
            'actual_duration', 'actual_price'  # Новые поля
        ]