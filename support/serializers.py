from rest_framework import serializers

from .models import FAQ, Policy, PolicySection, Ticket


class TicketSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "number", "topic", "booking_code", "message", "attachment", "status",
                  "status_label", "staff_reply", "created_at", "updated_at"]
        read_only_fields = ["status", "staff_reply"]

    def validate_attachment(self, f):
        if f and f.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Attachment must be under 5 MB.")
        return f


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ["id", "question", "answer"]


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicySection
        fields = ["heading", "body"]


class PolicySerializer(serializers.ModelSerializer):
    sections = SectionSerializer(many=True, read_only=True)

    class Meta:
        model = Policy
        fields = ["key", "title", "updated", "sections"]
