from rest_framework import generics
from .models import RoomType, Room
from .serializers import RoomTypeSerializer, RoomSerializer, RoomTypeAvailabilitySerializer, RoomTypeDetailSerializer
from rest_framework.exceptions import ValidationError
from datetime import datetime, date
from rest_framework.response import Response
from rest_framework import status
from .services import get_available_rooms_for_type, generate_booking_plans
from rest_framework.views import APIView

class RoomTypeCreateView(generics.CreateAPIView):
    
    serializer_class = RoomTypeSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room_type = serializer.save()
        return Response(
            RoomTypeSerializer(room_type).data, 
            status=status.HTTP_201_CREATED
        )
class RoomCreateView(generics.CreateAPIView):
    serilalizer_class = RoomSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = serializer.save()
        return Response(
            RoomSerializer(room).data,
            status=status.HTTP_201_CREATED
        )
        
class RoomTypeSearchView(generics.ListAPIView):
    serializer_class = RoomTypeAvailabilitySerializer
    
    def get_queryset(self):
        # 1. Get query parameters
        check_in_str = self.request.query_params.get('check_in')
        check_out_str = self.request.query_params.get('check_out')
        adults_str = self.request.query_params.get('adults')
        children_str = self.request.query_params.get('children', '0')
        
        # 2. Validate required parameters
        if not check_in_str or not check_out_str or not adults_str:
            raise ValidationError({
                "error": "check_in, check_out, and adults are required parameters"
            })
        
        # 3. Parse dates
        try:
            check_in = datetime.strptime(check_in_str, '%Y-%m-%d').date()
            check_out = datetime.strptime(check_out_str, '%Y-%m-%d').date()
        except ValueError:
            raise ValidationError({
                "error": "Invalid date format. Use YYYY-MM-DD"
            })
        
        # 4. Parse guest counts
        try:
            adults = int(adults_str)
            children = int(children_str)
        except ValueError:
            raise ValidationError({
                "error": "adults and children must be valid integers"
            })
        
        # 5. Validate dates and guest counts
        if check_in < date.today():
            raise ValidationError({"check_in": "Check-in date cannot be in the past"})
        
        if check_out <= check_in:
            raise ValidationError({"check_out": "Check-out must be after check-in"})
        
        if adults < 1:
            raise ValidationError({"adults": "At least one adult is required"})
        
        if children < 0:
            raise ValidationError({"children": "Number of children cannot be negative"})
        
        # 6. Filter room types by capacity
        room_types = RoomType.objects.filter(
            max_adults__gte=adults,
            max_children__gte=children
        )
        
        # 7. Check availability for each room type
        available_room_types = []
        for room_type in room_types:
            available_rooms = get_available_rooms_for_type(
                room_type=room_type,
                check_in_date=check_in,
                check_out_date=check_out
            )
            
            if available_rooms.exists():
                available_room_types.append(room_type.id)
        
        # 8. Return only available room types
        return RoomType.objects.filter(id__in=available_room_types)
    
    def get_serializer_context(self):
        """Pass dates to serializer for pricing calculation"""
        context = super().get_serializer_context()
        
        # Get dates from query params
        check_in_str = self.request.query_params.get('check_in')
        check_out_str = self.request.query_params.get('check_out')
        
        if check_in_str and check_out_str:
            try:
                check_in = datetime.strptime(check_in_str, '%Y-%m-%d').date()
                check_out = datetime.strptime(check_out_str, '%Y-%m-%d').date()
                
                context['check_in_date'] = check_in
                context['check_out_date'] = check_out
            except ValueError:
                pass
        
        return context
    
    def list(self, request, *args, **kwargs):
        """Override to add booking plans when no single room fits"""
        # Get normal search results
        queryset = self.get_queryset()
        
        # Get query params
        adults = int(request.query_params.get('adults', 0))
        children = int(request.query_params.get('children', 0))
        check_in_str = request.query_params.get('check_in')
        check_out_str = request.query_params.get('check_out')
        
        # Serialize normal results
        serializer = self.get_serializer(queryset, many=True)
        
        # Build response
        response_data = {
            'room_types': serializer.data,
            'booking_plans': None
        }
        
        # Check if any single room can fit everyone
        can_fit_in_one = queryset.exists()
        
        # If no single room fits, generate booking plans
        if not can_fit_in_one:
            check_in = datetime.strptime(check_in_str, '%Y-%m-%d').date()
            check_out = datetime.strptime(check_out_str, '%Y-%m-%d').date()
            
            plans = generate_booking_plans(check_in, check_out, adults, children)
            
            # Format plans for response
            response_data['booking_plans'] = {
                'budget_friendly': self._format_plans(plans['budget_friendly']),
                'convenience': self._format_plans(plans['convenience'])
            }
        
        return Response(response_data)
    
    def _format_plans(self, plans):
        """Format plans for JSON response"""
        formatted = []
        for plan in plans:
            rooms_list = []
            for room_type, count in plan['rooms'].items():
                rooms_list.append({
                    'room_type_id': room_type.id,
                    'room_type_name': room_type.name,
                    'room_type_slug': room_type.slug,
                    'count': count,
                    'capacity': f"{room_type.max_adults} adults, {room_type.max_children} children"
                })
            
            formatted.append({
                'rooms': rooms_list,
                'total_rooms': plan['total_rooms'],
                'total_price': str(plan['total_price']),
                'price_per_night': str(plan['price_per_night'])
            })
        
        return formatted

class RoomTypeDetailView(generics.RetrieveAPIView):
    queryset = RoomType.objects.prefetch_related('amenities', 'images', 'rooms')
    serializer_class = RoomTypeDetailSerializer
    lookup_field = 'slug' 
