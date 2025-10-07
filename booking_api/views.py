from django.db.models.functions import TruncDate
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta, datetime
import json

from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView

# Добавляем новые импорты для работы с Telegram API и сервисом
from .models import Service, Appointment, Employee, Client, Organization
from .serializers import (
    ServiceSerializer, AppointmentSerializer,
    AppointmentDetailSerializer, EmployeeSerializer,
)
# ИМПОРТ НОВОГО СЕРВИСА
from .services import BookingService
from .utils import calculate_available_slots  # Эту функцию можно будет удалить, заменив на сервис
from .notifications import send_appointment_confirmation
from .telegram_utils import send_telegram_notification


# --- НОВОЕ ПРЕДСТАВЛЕНИЕ: Для получения списка мастеров, привязанных к услуге ---
class EmployeeViewSet(viewsets.ReadOnlyModelViewSet):
    # ... (Оставить код без изменений)
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = self.queryset

        organization_id = self.request.query_params.get('organization_id')
        service_id = self.request.query_params.get('service_id')

        # 1. Фильтруем по организации (обязательно)
        if organization_id:
            try:
                org_id = int(organization_id)
                queryset = queryset.filter(organization_id=org_id)
            except ValueError:
                return self.queryset.none()
        else:
            return self.queryset.none()

        # 2. Фильтруем по услуге
        if service_id:
            try:
                svc_id = int(service_id)
                queryset = queryset.filter(services__id=svc_id).distinct()
            except ValueError:
                return self.queryset.none()

        return queryset


# --- ServiceViewSet (ОБНОВЛЕНО: Добавлен эндпоинт для Telegram) ---
class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """API для просмотра списка доступных Услуг/Работ."""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        # ... (Оставить основную логику фильтрации по organization_id)
        organization_id = self.request.query_params.get('organization_id')
        if organization_id:
            return self.queryset.filter(organization_id=organization_id)
        return self.queryset.none()

    # НОВЫЙ ЭНДПОИНТ: GET /api/v1/services/telegram_catalog/?org_id=1
    @action(detail=False, methods=['get'], permission_classes=[AllowAny], url_path='telegram_catalog')
    def telegram_catalog(self, request):
        """
        Возвращает список активных услуг в формате, сгруппированном по категории,
        оптимизированном для Telegram-бота. Требуется org_id.
        """
        organization_id = request.query_params.get('org_id')
        if not organization_id:
            return Response({"error": "Требуется org_id."}, status=status.HTTP_400_BAD_REQUEST)

        active_services = self.get_queryset().filter(organization_id=organization_id).order_by('category', 'name')

        categorized_data = {}

        for service in active_services:
            # Получаем ID мастеров, которые могут оказать эту услугу
            employee_ids = list(service.employees.values_list('id', flat=True))

            service_data = {
                'id': service.id,
                'name': service.name,
                'category': service.category or 'Без категории',
                'price': float(service.base_price),
                'duration_minutes': service.base_duration,
                'total_time_minutes': service.total_duration,
                'employee_ids': employee_ids,  # Список доступных мастеров
            }

            category = service.category if service.category else 'Без категории'
            if category not in categorized_data:
                categorized_data[category] = []
            categorized_data[category].append(service_data)

        return Response(categorized_data, status=status.HTTP_200_OK)


# --- Представление для работы с записями (с разделением разрешений) ---
class AppointmentViewSet(viewsets.ModelViewSet):
    queryset = Appointment.objects.all().order_by('-start_time')

    def get_serializer_class(self):
        if self.action == 'create':
            return AppointmentSerializer
        return AppointmentDetailSerializer

    def get_permissions(self):
        if self.action in ['create', 'list_available_slots', 'list']:
            self.permission_classes = [AllowAny]
        else:
            self.permission_classes = [IsAuthenticated]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = serializer.save()
        send_appointment_confirmation(appointment)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    # ОБНОВЛЕННЫЙ ЭНДПОИНТ: GET /api/v1/appointments/available_slots/
    @action(detail=False, methods=['get'], permission_classes=[AllowAny], url_path='available_slots')
    def list_available_slots(self, request):
        """
        Возвращает доступное время для бронирования с учетом плавающих расписаний,
        блокировок и записей, используя BookingService.
        """
        employee_id = request.query_params.get('employee_id')
        service_id = request.query_params.get('service_id')
        date_str = request.query_params.get('date')

        if not all([employee_id, service_id, date_str]):
            return Response(
                {"error": "Требуются параметры: employee_id, service_id, date."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            employee = Employee.objects.get(pk=employee_id)
            service = Service.objects.get(pk=service_id)
            booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (Employee.DoesNotExist, Service.DoesNotExist) as e:
            return Response({"error": f"Объект не найден: {e}"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"error": "Неверный формат даты. Ожидается YYYY-MM-DD."},
                            status=status.HTTP_400_BAD_REQUEST)

        # *** Использование BookingService для расчета ***
        try:
            booking_service = BookingService(employee, service, booking_date)
            available_slots = booking_service.get_available_slots()

            # Форматирование объектов datetime в строки ISO для ответа
            slots_data = [slot.isoformat() for slot in available_slots]

            return Response({
                "employee_name": employee.name,
                "date": date_str,
                "service_total_duration_min": service.total_duration,
                "available_slots": slots_data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            # Сюда могут попасть ошибки из логики get_working_intervals или _subtract_intervals
            return Response({"error": f"Ошибка при расчете слотов: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- ПРЕДСТАВЛЕНИЕ ДЛЯ TELEGRAM (Создание Записи) ---
class TelegramAppointmentCreationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        data = request.data
        required_fields = ['client_name', 'client_phone', 'address', 'service', 'employee', 'start_time',
                           'organization']
        if not all(field in data for field in required_fields):
            return Response({
                'message': 'Отсутствуют обязательные поля: client_name, client_phone, address, service, employee, start_time, organization.'},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            # 1. Находим или создаем Клиента
            client, created = Client.objects.get_or_create(
                phone_number=data['client_phone'],
                defaults={'name': data['client_name']}
            )
            if not created and client.name != data['client_name']:
                client.name = data['client_name']
                client.save()

            # 2. Получаем связанные объекты
            service = Service.objects.get(id=data['service'])
            employee = Employee.objects.get(id=data['employee'])
            organization = Organization.objects.get(id=data['organization'])

            start_time_unaware = datetime.strptime(data['start_time'], '%Y-%m-%d %H:%M')
            # Важно: используем timezone.make_aware, чтобы соответствовать DateTimeField
            start_time = timezone.make_aware(start_time_unaware, timezone.get_current_timezone())

            # 3. Расчет времени окончания и проверка конфликтов
            total_duration = service.total_duration
            end_time = start_time + timedelta(minutes=total_duration)

            # Проверка конфликта: ищем записи, которые пересекаются с новым интервалом
            conflict = Appointment.objects.filter(
                employee=employee,
                # Запись заканчивается после начала новой
                end_time__gt=start_time,
                # Запись начинается до окончания новой
                start_time__lt=end_time
            ).exists()

            if conflict:
                return Response({'message': 'Выбранное время уже занято, попробуйте другое.'},
                                status=status.HTTP_409_CONFLICT)

            # 4. Создание записи
            new_appointment = Appointment.objects.create(
                organization=organization,
                client=client,
                employee=employee,
                service=service,
                address=data['address'],
                start_time=start_time,
                # end_time рассчитывается в save(), но можно установить и здесь для чистоты
                # Лучше дать save() делать свое дело, но для TelegramAPI явно указываем.
                end_time=end_time,
                status='CONFIRMED',  # Считаем, что бот подтверждает запись
                # Также можно добавить client_chat_id, если он приходит в запросе:
                client_chat_id=data.get('client_chat_id')
            )

            # Важно: Сразу после создания запускаем save(), чтобы end_time обновился
            # на основе custom_duration, если он был бы передан.
            # В данном случае, Appointment.save() уже был переопределен для расчета end_time.

            # 5. Мгновенное оповещение Мастера
            send_appointment_confirmation(new_appointment)

            return Response({
                'message': 'Запись успешно создана через Telegram API.',
                'appointment_id': new_appointment.id,
                'client_name': client.name,
                'start_time': start_time.isoformat()
            }, status=status.HTTP_201_CREATED)

        except (Service.DoesNotExist, Employee.DoesNotExist, Organization.DoesNotExist):
            return Response({'message': 'Неверный ID услуги, мастера или организации.'},
                            status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({'message': 'Неверный формат start_time (ожидается YYYY-MM-DD HH:MM).'},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'message': f'Ошибка сервера: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- Представление для Аналитики и Отчетов (Требуется авторизация) ---
class AnalyticsViewSet(APIView):
    # ... (Код без изменений)
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        days_to_look_back = 7
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days_to_look_back)

        report_data = Appointment.objects.filter(
            start_time__gte=start_date,
            status__in=['PENDING', 'CONFIRMED']
        ).annotate(
            date=TruncDate('start_time')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')

        formatted_data = [
            {
                "date": item['date'].strftime('%Y-%m-%d'),
                "appointments_count": item['count']
            }
            for item in report_data
        ]

        return Response({
            "report_period": f"Последние {days_to_look_back} дней",
            "data": formatted_data
        })