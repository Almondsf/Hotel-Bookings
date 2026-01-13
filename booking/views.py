from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import BookingCreateSerializer, BookingConfirmationSerializer

class CreateBookingView(CreateAPIView):
    serializer_class = BookingCreateSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            booking = serializer.save()
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        confirmation_serializer = BookingConfirmationSerializer(booking)
        return Response(confirmation_serializer.data, status=status.HTTP_201_CREATED)