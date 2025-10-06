# booking_api/views.py

from django.db.models.functions import TruncDate
from django.db.models import Count, Q  # Импортируем Q для сложной фильтрации
from datetime import timedelta
from django.utils import timezone

from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView

from .models import Service, Appointment, Employee, Client
# ! ПРЕДПОЛАГАЕТСЯ, ЧТО ВЫ СОЗДАЛИ EmployeeSerializer !
from .serializers import ServiceSerializer, AppointmentSerializer, AppointmentDetailSerializer, EmployeeSerializer
from .utils import calculate_available_slots
from .notifications import send_appointment_confirmation


# --- НОВОЕ ПРЕДСТАВЛЕНИЕ: Для получения списка мастеров, привязанных к услуге ---
class EmployeeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для просмотра списка Сотрудников/Мастеров.
    Позволяет фильтровать по service_id и organization_id.
    """
    queryset = Employee.objects.all()
    # ! Убедитесь, что у вас есть EmployeeSerializer !
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
                # Если ID организации не число, возвращаем пустой набор
                return self.queryset.none()
        else:
            # Если нет ID организации, возвращаем пустой набор
            return self.queryset.none()

        # 2. Фильтруем по услуге (КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ)
        if service_id:
            try:
                svc_id = int(service_id)

                # ИСПРАВЛЕНО: Согласно трассировке, правильный ключ - 'services'
                queryset = queryset.filter(services__id=svc_id).distinct()

            except ValueError:
                # Если ID услуги не число, возвращаем пустой набор
                return self.queryset.none()

        return queryset


# --- Представление для списка услуг (публичное) ---
class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """API для просмотра списка доступных Услуг/Работ."""
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        organization_id = self.request.query_params.get('organization_id')
        if organization_id:
            return self.queryset.filter(organization_id=organization_id)
        return self.queryset.none()


# --- Представление для работы с записями (с разделением разрешений) ---
class AppointmentViewSet(viewsets.ModelViewSet):
    """
    API для создания (AllowAny) и управления (IsAuthenticated) записями.
    """
    queryset = Appointment.objects.all().order_by('-start_time')

    def get_serializer_class(self):
        if self.action == 'create':
            return AppointmentSerializer
        return AppointmentDetailSerializer

    def get_permissions(self):
        if self.action in ['create', 'list_available_slots', 'list']:  # list добавлен для удобства
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

    # Обновленный метод для получения доступных слотов (КРИТИЧНО)
    # GET /api/v1/appointments/available_slots/?org_id=1&service_id=2&date=2025-10-15&employee_id=1
    @action(detail=False, methods=['get'], permission_classes=[AllowAny], url_path='available_slots')
    def list_available_slots(self, request):
        organization_id = request.query_params.get('org_id')
        service_id = request.query_params.get('service_id')
        date_str = request.query_params.get('date')
        employee_id = request.query_params.get('employee_id')  # ID мастера

        # employee_id теперь является опциональным, но желательным параметром для точного расчета
        if not all([organization_id, service_id, date_str]):
            return Response(
                {"error": "Требуются параметры: org_id, service_id, date."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Вызываем рабочую логику расчета, передавая employee_id
        available_slots = calculate_available_slots(
            int(organization_id),
            int(service_id),
            date_str,
            employee_id=int(employee_id) if employee_id else None  # Передаем employee_id
        )

        # 2. Обрабатываем возможные ошибки
        if isinstance(available_slots, dict) and 'error' in available_slots:
            status_code = available_slots.get('status', status.HTTP_400_BAD_REQUEST)
            return Response(available_slots, status=status_code)

        return Response(available_slots)


# --- Представление для Аналитики и Отчетов (Требуется авторизация) ---
class AnalyticsViewSet(APIView):
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