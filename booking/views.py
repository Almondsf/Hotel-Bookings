from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import BookingCreateSerializer, BookingConfirmationSerializer
from rest_framework.views import APIView

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
    
class BookingLookupView(APIView):
    
    def post(self, request, *args, **kwargs):
        confirmation_number = request.data.get('confirmation_number')
        email = request.data.get('email')
        
        # Validate both are provided
        if not confirmation_number or not email:
            return Response(
                {"error": "Both confirmation_number and email are required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Look up booking
        try:
            booking = Booking.objects.get(confirmation_number=confirmation_number)
        except Booking.DoesNotExist:
            return Response(
                {"error": "Booking not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verify email matches
        if booking.guest.email != email:
            return Response(
                {"error": "Email does not match booking records."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Return booking details
        serializer = BookingConfirmationSerializer(booking)
        return Response(serializer.data, status=status.HTTP_200_OK)