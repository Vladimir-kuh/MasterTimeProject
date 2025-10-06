# booking_api/views.py

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

# Добавляем новые импорты для работы с Telegram API
from .models import Service, Appointment, Employee, Client, Organization
from .serializers import (
    ServiceSerializer, AppointmentSerializer,
    AppointmentDetailSerializer, EmployeeSerializer,
    # Если вы создадите TelegramAppointmentSerializer, используйте его здесь
)
from .utils import calculate_available_slots
from .notifications import send_appointment_confirmation  # Убедитесь, что он использует telegram_utils
from .telegram_utils import send_telegram_notification  # (для прямого использования в Telegram API)


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
    # ... (Оставить код без изменений, он уже обрабатывает создание через DRF)
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
        send_appointment_confirmation(appointment)  # В этой функции теперь Telegram-уведомление
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    # ... (list_available_slots без изменений)
    @action(detail=False, methods=['get'], permission_classes=[AllowAny], url_path='available_slots')
    def list_available_slots(self, request):
        # ... (Код без изменений)
        organization_id = request.query_params.get('org_id')
        service_id = request.query_params.get('service_id')
        date_str = request.query_params.get('date')
        employee_id = request.query_params.get('employee_id')

        if not all([organization_id, service_id, date_str]):
            return Response(
                {"error": "Требуются параметры: org_id, service_id, date."},
                status=status.HTTP_400_BAD_REQUEST
            )

        available_slots = calculate_available_slots(
            int(organization_id),
            int(service_id),
            date_str,
            employee_id=int(employee_id) if employee_id else None
        )

        if isinstance(available_slots, dict) and 'error' in available_slots:
            status_code = available_slots.get('status', status.HTTP_400_BAD_REQUEST)
            return Response(available_slots, status=status_code)

        return Response(available_slots)


# --- ПРЕДСТАВЛЕНИЕ ДЛЯ TELEGRAM (Создание Записи) ---
# Используем отдельный APIView для прямого POST-запроса от Telegram-бота
class TelegramAppointmentCreationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # Нам нужен кастомный десериализатор, чтобы найти или создать Client
        # Для простоты используем AppointmentSerializer и ищем/создаем Client вручную

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
            start_time = timezone.make_aware(start_time_unaware)

            # 3. Расчет времени окончания и проверка конфликтов
            total_duration = service.total_duration
            end_time = start_time + timedelta(minutes=total_duration)

            conflict = Appointment.objects.filter(
                employee=employee,
                end_time__gt=start_time,
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
                # end_time рассчитывается в save(), но мы можем установить его здесь
                end_time=end_time,
                status='CONFIRMED'  # Считаем, что бот подтверждает запись
            )

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