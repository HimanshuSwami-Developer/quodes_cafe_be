from rest_framework import generics, permissions
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from catalog.models import CafeSettings

from . import notify
from .models import FAQ, Policy
from .serializers import FAQSerializer, PolicySerializer, TicketSerializer


class TicketListCreate(generics.ListCreateAPIView):
    serializer_class = TicketSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return self.request.user.tickets.all()[:20]

    def perform_create(self, serializer):
        t = serializer.save(user=self.request.user)
        t._cafe = CafeSettings.get()
        notify.created(t)


class FAQList(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = FAQSerializer
    queryset = FAQ.objects.all()
    pagination_class = None


class PolicyList(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = PolicySerializer
    queryset = Policy.objects.prefetch_related("sections")
    pagination_class = None
