#!/usr/bin/env python3
"""
Presto Flight Card Display Client

Connects to the flight tracker server and displays flight information
on a Pimoroni Presto display. Designed for MicroPython on the Presto device.
"""

import sys
import json
import time

# MicroPython compatibility
try:
    import network
    HAS_NETWORK = True
except ImportError:
    HAS_NETWORK = False

try:
    import urequests as requests
    HAS_REQUESTS_EXCEPTIONS = False
except ImportError:
    try:
        import requests
        HAS_REQUESTS_EXCEPTIONS = hasattr(requests, 'exceptions')
    except ImportError:
        requests = None
        HAS_REQUESTS_EXCEPTIONS = False

try:
    import presto
    HAS_PRESTO = True
except ImportError:
    HAS_PRESTO = False
    presto = None

try:
    import picovector
except ImportError:
    picovector = None

try:
    from plasma import WS2812
    HAS_PLASMA = True
except ImportError:
    HAS_PLASMA = False
    WS2812 = None

# Try to import typing (not available in MicroPython)
try:
    from typing import Optional, Dict, List, Any
except ImportError:
    pass


class PrestoFlightClient:
    """Client for displaying flight information on Presto display"""
    
    def __init__(self, server_url="http://piaware.local:5050", wifi_ssid=None, wifi_password=None):
        self.server_url = server_url.rstrip('/')
        self.events_url = f"{self.server_url}/events"
        self.current_flight = None
        
        # Initialize display
        self.presto = None
        self.display = None
        self.vector = None
        self.display_width = 480
        self.display_height = 480
        
        # Touch handling for double tap to toggle backlight
        self.last_tap_time = 0
        self.tap_timeout = 0.5  # 500ms window for double tap
        self.backlight_on = True
        self.backlight_leds = None  # Will hold WS2812 instance for LED control
        
        if HAS_PRESTO:
            try:
                # Initialize Presto with ambient light (as per working example)
                self.presto = presto.Presto(ambient_light=True)
                self.display = self.presto.display
                
                # Get dimensions using the correct API
                try:
                    self.display_width, self.display_height = self.display.get_bounds()
                except AttributeError:
                    # Fallback: use known Presto dimensions
                    self.display_width = 480
                    self.display_height = 480
                    print(f"   Using default dimensions: {self.display_width}x{self.display_height}")
                
                # Create pens for colors (using Presto's create_pen API)
                self.black_pen = self.display.create_pen(0, 0, 0)
                self.gray_pen = self.display.create_pen(100, 100, 100)
                self.white_pen = self.display.create_pen(255, 255, 255)
                # Flight card colors (inspired by FlightAware)
                self.header_blue_pen = self.display.create_pen(30, 64, 175)  # Blue header
                self.accent_blue_pen = self.display.create_pen(59, 130, 246)  # Lighter blue
                self.dark_gray_pen = self.display.create_pen(60, 60, 60)
                self.light_gray_pen = self.display.create_pen(200, 200, 200)
                
                # Initialize picovector for custom font support
                # See: https://github.com/pimoroni/presto/blob/main/examples/indoor-outdoor-temp.py
                self.vector = None
                self.use_vector_font = False
                try:
                    if HAS_PRESTO and picovector:
                        self.vector = picovector.PicoVector(self.display)
                        print("   ✓ PicoVector initialized")
                        
                        # Try to load custom Roboto font using picovector
                        font_paths = [
                            "Roboto-Medium.af",
                            "/Roboto-Medium.af",
                            "/fonts/Roboto-Medium.af"
                        ]
                        
                        font_loaded = False
                        for font_path in font_paths:
                            try:
                                # Set font using picovector (as per example)
                                # The second parameter is the default size
                                self.vector.set_font(font_path, 48)
                                self.use_vector_font = True
                                print(f"   ✓ Loaded custom Roboto font from: {font_path}")
                                font_loaded = True
                                break
                            except Exception as e:
                                print(f"   Tried {font_path}: {e}")
                                continue
                        
                        if not font_loaded:
                            print("   Custom font not found, will use display.text() with built-in fonts")
                    else:
                        print("   PicoVector not available")
                except Exception as e:
                    print(f"   PicoVector initialization error: {e}")
                    import sys
                    try:
                        sys.print_exception(e)
                    except:
                        pass
                    self.vector = None
                
                # Set up built-in font fallback
                self.font = None
                if not self.use_vector_font and hasattr(self.display, 'set_font'):
                    # Try different built-in fonts in order of preference
                    font_options = [
                        "bitmap14_outline",  # Best readability, outlined
                        "bitmap14",          # Large, clean
                        "bitmap8",           # Medium, good balance
                        "bitmap6"            # Small, compact
                    ]
                    
                    for font_name in font_options:
                        try:
                            self.display.set_font(font_name)
                            self.font = font_name
                            print(f"   ✓ Using built-in {font_name} font")
                            break
                        except:
                            continue
                
                # Clear display (set pen first, then clear)
                self.display.set_pen(self.white_pen)
                self.display.clear()
                self.presto.update()
                
                # Initialize LEDs to off
                # Try multiple methods: direct plasma.WS2812, presto.set_led_rgb, or presto.backlight attribute
                try:
                    # Method 1: Try using plasma.WS2812 directly (as per Presto docs)
                    if HAS_PLASMA and WS2812:
                        try:
                            self.backlight_leds = WS2812(7, 0, 0, 33)  # 7 LEDs, pin info from docs
                            for i in range(7):
                                self.backlight_leds.set_rgb(i, 0, 0, 0)
                            if hasattr(self.backlight_leds, 'start'):
                                self.backlight_leds.start()
                            elif hasattr(self.backlight_leds, 'show'):
                                self.backlight_leds.show()
                            print("   ✓ LEDs initialized to OFF (using plasma.WS2812)")
                        except Exception as e:
                            print(f"   ⚠️  plasma.WS2812 failed: {e}")
                            self.backlight_leds = None
                    
                    # Method 2: Try presto.set_led_rgb (if available)
                    if not self.backlight_leds and hasattr(self.presto, 'set_led_rgb'):
                        for i in range(7):
                            self.presto.set_led_rgb(i, 0, 0, 0)
                        print("   ✓ LEDs initialized to OFF (using presto.set_led_rgb)")
                    
                    # Method 3: Check if presto has a backlight attribute that controls LEDs
                    if not self.backlight_leds and hasattr(self.presto, 'backlight'):
                        try:
                            # Check if backlight is an object with LED control
                            bl = self.presto.backlight
                            if hasattr(bl, 'set_rgb'):
                                for i in range(7):
                                    bl.set_rgb(i, 0, 0, 0)
                                if hasattr(bl, 'start'):
                                    bl.start()
                                elif hasattr(bl, 'show'):
                                    bl.show()
                                print("   ✓ LEDs initialized to OFF (using presto.backlight)")
                        except:
                            pass
                            
                except Exception as e:
                    print(f"   ⚠️  LED initialization error: {e}")
                    import sys
                    try:
                        sys.print_exception(e)
                    except:
                        pass
                
                # Initialize touch handling if available
                self.touch = None
                if hasattr(self.presto, 'touch'):
                    self.touch = self.presto.touch
                    print("   ✓ Touch input available")
                    # Test touch object attributes
                    print(f"   Touch object: {self.touch}")
                    print(f"   Touch has poll: {hasattr(self.touch, 'poll')}")
                    print(f"   Touch has state: {hasattr(self.touch, 'state')}")
                else:
                    print("   ⚠️  Touch input not available")
                
                print(f"✓ Presto display initialized ({self.display_width}x{self.display_height})")
            except Exception as e:
                print(f"⚠️ Warning: Error during Presto initialization: {e}")
                import sys
                try:
                    sys.print_exception(e)
                except:
                    pass
                # Don't lose the display object if presto was created
                if hasattr(self, 'presto') and self.presto:
                    try:
                        self.display = self.presto.display
                        print("   Display object recovered")
                    except:
                        self.display = None
                        self.presto = None
                else:
                    self.display = None
                    self.presto = None
                self.display_width = 480
                self.display_height = 480
                self.vector = None
        else:
            print("⚠️ Presto library not available - running in simulation mode")
        
        # Connect WiFi if needed
        if HAS_NETWORK and (wifi_ssid or self._load_wifi_config()):
            if wifi_ssid:
                self._connect_wifi(wifi_ssid, wifi_password)
            else:
                config = self._load_wifi_config()
                if config:
                    self._connect_wifi(config.get('WIFI_SSID'), config.get('WIFI_PASSWORD'))
    
    def _load_wifi_config(self):
        """Load WiFi configuration from file"""
        try:
            # Try Python file first
            try:
                import wifi_config
                return {
                    'WIFI_SSID': getattr(wifi_config, 'WIFI_SSID', None),
                    'WIFI_PASSWORD': getattr(wifi_config, 'WIFI_PASSWORD', None)
                }
            except ImportError:
                pass
            
            # Try JSON file
            try:
                with open('wifi_config.json', 'r') as f:
                    return json.load(f)
            except (OSError, IOError, ValueError):
                pass
        except Exception as e:
            print(f"⚠️ Could not load WiFi config: {e}")
        return None
    
    def _connect_wifi(self, ssid, password):
        """Connect to WiFi network"""
        if not HAS_NETWORK:
            print("⚠️ Network module not available")
            return False
        
        if not ssid or not password:
            print("⚠️ WiFi SSID or password not provided")
            return False
        
        print(f"Connecting to WiFi: {ssid}...")
        
        try:
            wlan = network.WLAN(network.STA_IF)
            wlan.active(True)
            
            if not wlan.isconnected():
                wlan.connect(ssid, password)
                
                # Wait for connection
                max_wait = 20
                while max_wait > 0:
                    if wlan.isconnected():
                        break
                    max_wait -= 1
                    time.sleep(1)
                
                if wlan.isconnected():
                    ip = wlan.ifconfig()[0]
                    print(f"✓ WiFi connected! IP: {ip}")
                    return True
                else:
                    print("✗ WiFi connection failed")
                    return False
            else:
                ip = wlan.ifconfig()[0]
                print(f"✓ Already connected to WiFi. IP: {ip}")
                return True
        except Exception as e:
            print(f"✗ WiFi connection error: {e}")
            return False
    
    def clear_display(self):
        """Clear the display"""
        if self.display:
            try:
                self.display.set_pen(self.white_pen)
                self.display.clear()
            except:
                self.display.clear()
    
    def check_touch_events(self):
        """Check for touch events and handle double tap to toggle backlight
        Based on Presto touch API: https://github.com/pimoroni/presto/blob/main/examples/awesome_game.py
        """
        if not self.touch or not self.presto:
            return
        
        try:
            # Initialize last touch state if not exists
            if not hasattr(self, '_last_touch_state'):
                self._last_touch_state = False
            
            # Poll touch to update state (as per Presto examples)
            self.touch.poll()
            
            # Check touch.state (boolean - True when touched)
            current_touch_state = bool(self.touch.state)
            
            # Debug: print touch state occasionally (every 20 calls to see activity)
            if not hasattr(self, '_touch_debug_counter'):
                self._touch_debug_counter = 0
            self._touch_debug_counter += 1
            if self._touch_debug_counter % 20 == 0:
                print(f"   [Touch check #{self._touch_debug_counter}] state={current_touch_state}, last={self._last_touch_state}")
            
            # Detect touch press (transition from False to True)
            if current_touch_state and not self._last_touch_state:
                current_time = time.time()
                time_since_last_tap = current_time - self.last_tap_time
                
                print(f"   👆👆👆 Touch PRESS detected! (time since last: {time_since_last_tap:.3f}s)")
                
                # Check if this is a double tap (within timeout window)
                if self.last_tap_time > 0 and time_since_last_tap < self.tap_timeout:
                    # Double tap detected - toggle backlight
                    print(f"   👆👆 Double tap detected! Toggling backlight...")
                    self.toggle_backlight()
                    self.last_tap_time = 0  # Reset to prevent triple tap
                else:
                    # First tap - record time
                    print(f"   👆 First tap - waiting for second tap (need within {self.tap_timeout}s)...")
                    self.last_tap_time = current_time
            
            # Update last touch state
            self._last_touch_state = current_touch_state
                
        except Exception as e:
            # Touch not available or error reading touch - log the error
            print(f"   ⚠️  Touch check error: {e}")
            import sys
            try:
                sys.print_exception(e)
            except:
                pass
    
    def toggle_backlight(self):
        """Toggle the display backlight and LEDs on/off"""
        if not self.presto:
            return
        
        try:
            self.backlight_on = not self.backlight_on
            
            # Backlight value: 1.0 = on, 0.0 = off (as per error message)
            backlight_value = 1.0 if self.backlight_on else 0.0
            
            # Try different methods to control backlight
            if hasattr(self.presto, 'set_backlight'):
                self.presto.set_backlight(backlight_value)
            elif hasattr(self.presto, 'backlight'):
                self.presto.backlight(backlight_value)
            elif hasattr(self.display, 'set_backlight'):
                self.display.set_backlight(backlight_value)
            elif hasattr(self.display, 'backlight'):
                self.display.backlight(backlight_value)
            else:
                # Fallback: try to access backlight attribute directly
                try:
                    if hasattr(self.presto, 'backlight_level'):
                        self.presto.backlight_level = backlight_value
                except:
                    pass
            
            # Toggle LEDs on the back of Presto
            # Try multiple methods to ensure LEDs are controlled
            try:
                led_status = "ON" if self.backlight_on else "OFF"
                print(f"   💡 Setting LEDs to {led_status}...")
                
                # Method 1: Use plasma.WS2812 if we have it
                if self.backlight_leds:
                    for i in range(7):
                        if self.backlight_on:
                            self.backlight_leds.set_rgb(i, 20, 20, 30)
                        else:
                            self.backlight_leds.set_rgb(i, 0, 0, 0)
                    # Apply changes
                    if hasattr(self.backlight_leds, 'start'):
                        self.backlight_leds.start()
                    elif hasattr(self.backlight_leds, 'show'):
                        self.backlight_leds.show()
                    print(f"   ✓ LEDs set to {led_status} (using plasma.WS2812)")
                
                # Method 2: Try presto.set_led_rgb (fallback or additional)
                if hasattr(self.presto, 'set_led_rgb'):
                    for i in range(7):
                        if self.backlight_on:
                            self.presto.set_led_rgb(i, 20, 20, 30)
                        else:
                            self.presto.set_led_rgb(i, 0, 0, 0)
                    print(f"   ✓ LEDs set to {led_status} (using presto.set_led_rgb)")
                
                # Method 3: Try presto.backlight attribute
                if hasattr(self.presto, 'backlight'):
                    try:
                        bl = self.presto.backlight
                        if hasattr(bl, 'set_rgb'):
                            for i in range(7):
                                if self.backlight_on:
                                    bl.set_rgb(i, 20, 20, 30)
                                else:
                                    bl.set_rgb(i, 0, 0, 0)
                            if hasattr(bl, 'start'):
                                bl.start()
                            elif hasattr(bl, 'show'):
                                bl.show()
                            print(f"   ✓ LEDs set to {led_status} (using presto.backlight)")
                    except Exception as e:
                        print(f"   ⚠️  presto.backlight failed: {e}")
                        
            except Exception as e:
                print(f"   ⚠️  Could not toggle LEDs: {e}")
                import sys
                try:
                    sys.print_exception(e)
                except:
                    pass
            
            status = "ON" if self.backlight_on else "OFF"
            print(f"   💡 Backlight: {status} (value: {backlight_value})")
        except Exception as e:
            print(f"   ⚠️  Could not toggle backlight: {e}")
            import sys
            try:
                sys.print_exception(e)
            except:
                pass
    
    def draw_rectangle(self, x, y, width, height, pen):
        """Draw a filled rectangle"""
        if not self.display:
            return
        try:
            self.display.set_pen(pen)
            self.display.rectangle(x, y, width, height)
        except Exception as e:
            print(f"Error drawing rectangle: {e}")
    
    def draw_airplane_icon(self, x, y):
        """Draw airplane icon using the exact SVG path from FlightAware demo
        SVG path: M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z
        ViewBox: 0 0 24 24, so we need to scale and translate coordinates
        """
        if not self.display:
            return
        
        try:
            self.display.set_pen(self.accent_blue_pen)
            
            # Scale factor: SVG is 24x24, scale to about 32 pixels
            scale = 1.33
            center_x = int(x)
            center_y = int(y)
            
            # Translate SVG coordinates (0-24) to screen coordinates centered at (x, y)
            # SVG origin is top-left, we want to center the icon
            def svg_to_screen(svg_x, svg_y):
                # Center the 24x24 SVG in our coordinate space
                screen_x = center_x + int((svg_x - 12) * scale)
                screen_y = center_y + int((svg_y - 12) * scale)
                return screen_x, screen_y
            
            # Parse the SVG path manually and create polygon points
            # The path creates a filled airplane shape pointing right
            # Key points from the path (approximated, as curves are simplified):
            points = [
                (21, 16),   # Start
                (21, 14),   # v-2
                (13, 9),    # l-8-5
                (13, 3.5),  # V3.5
                (10, 3.5),  # After curve (simplified)
                (10, 9),    # V9
                (2, 14),    # l-8 5
                (2, 16),    # v2
                (10, 13.5), # l8-2.5
                (10, 19),   # V19
                (8, 20.5),  # l-2 1.5
                (8, 22),    # V22
                (11.5, 21), # l3.5-1
                (15, 22),   # 3.5 1
                (15, 20.5), # v-1.5
                (13, 19),   # L13 19
                (13, 13.5), # v-5.5
                (21, 16),   # l8 2.5 (back to start)
            ]
            
            # Convert to screen coordinates
            screen_points = [svg_to_screen(px, py) for px, py in points]
            
            # Draw filled polygon using scanline fill algorithm
            # Find bounding box
            min_y = min(py for _, py in screen_points)
            max_y = max(py for _, py in screen_points)
            
            # For each scanline, find intersections and fill
            for scan_y in range(min_y, max_y + 1):
                intersections = []
                num_points = len(screen_points)
                
                for i in range(num_points):
                    p1 = screen_points[i]
                    p2 = screen_points[(i + 1) % num_points]
                    
                    # Check if scanline intersects this edge
                    y1, y2 = p1[1], p2[1]
                    if y1 != y2 and min(y1, y2) <= scan_y < max(y1, y2):
                        # Calculate x intersection
                        x1, x2 = p1[0], p2[0]
                        if y2 != y1:
                            x_intersect = x1 + (scan_y - y1) * (x2 - x1) / (y2 - y1)
                            intersections.append(int(x_intersect))
                
                # Sort intersections and fill between pairs
                intersections.sort()
                for i in range(0, len(intersections) - 1, 2):
                    if i + 1 < len(intersections):
                        x_start = max(0, intersections[i])
                        x_end = min(self.display_width - 1, intersections[i + 1])
                        if x_end > x_start:
                            self.display.rectangle(x_start, scan_y, x_end - x_start + 1, 1)
            
        except Exception as e:
            print(f"Error drawing airplane icon: {e}")
            import sys
            try:
                sys.print_exception(e)
            except:
                pass
            # Fallback: simple arrow
            try:
                self.draw_text(x, y, "→", size=32, color=(59, 130, 246), center=True)
            except:
                pass
    
    def draw_text(self, x, y, text, size=20, color=(0, 0, 0), bold=False, center=False, right=False):
        """Draw text using PicoVector (for custom fonts) or display.text() (for built-in fonts)"""
        if not self.display:
            print(f"[SIM] Text at ({x}, {y}): {text} (size={size}, color={color}, bold={bold})")
            return
        
        try:
            # Select pen based on color
            r, g, b = color if isinstance(color, tuple) else (0, 0, 0)
            if r == 0 and g == 0 and b == 0:
                pen = self.black_pen
            elif r < 128 and g < 128 and b < 128:
                pen = self.gray_pen
            else:
                # Create custom pen for this color
                pen = self.display.create_pen(r, g, b)
            
            # Set the pen
            self.display.set_pen(pen)
            
            # Use PicoVector if custom font is loaded (as per example: https://github.com/pimoroni/presto/blob/main/examples/indoor-outdoor-temp.py)
            if hasattr(self, 'use_vector_font') and self.use_vector_font and self.vector:
                try:
                    # Set font size for vector (size parameter is in points)
                    # Roboto font sizes need to be adjusted - convert our size to points
                    # Our size parameter is roughly pixels, but vector uses points
                    # Use much more conservative scaling to prevent overlap
                    vector_size = int(size * 0.60)  # Much more conservative scaling for Roboto
                    if vector_size < 8:
                        vector_size = 8  # Minimum readable size
                    self.vector.set_font_size(vector_size)
                    
                    # Adjust x for alignment if requested
                    if center or right:
                        # Measure text to align it properly
                        try:
                            _, _, text_width, _ = self.vector.measure_text(text)
                            if center:
                                x = x - (text_width // 2)
                            elif right:
                                x = x - text_width
                        except:
                            # Fallback approximation
                            text_width = len(text) * (size * 0.4)
                            if center:
                                x = x - (text_width // 2)
                            elif right:
                                x = x - text_width
                    
                    # Ensure text doesn't go off screen
                    if x < 0:
                        x = 5
                    if x + len(text) * (size * 0.4) > self.display_width:
                        x = self.display_width - len(text) * (size * 0.4) - 5
                    
                    # Draw text using vector (this uses the custom Roboto font)
                    self.vector.text(text, int(x), int(y))
                    return
                except Exception as e:
                    print(f"Error drawing text with vector: {e}")
                    import sys
                    try:
                        sys.print_exception(e)
                    except:
                        pass
                    # Fall through to display.text()
            
            # Fallback: use display.text() with built-in fonts
            if hasattr(self, 'font') and self.font and hasattr(self.display, 'set_font'):
                try:
                    self.display.set_font(self.font)
                except:
                    pass
            
            # Adjust x for alignment if requested
            if center or right:
                # Approximate text width (rough estimate)
                text_width = len(text) * (size * 0.6)
                if center:
                    x = x - (text_width // 2)
                elif right:
                    x = x - text_width
            
            # Convert size to scale (Presto text uses scale, roughly size/10)
            # For bitmap fonts, scale affects size differently
            scale = max(1, int(size / 10))
            if scale < 1:
                scale = 1
            
            # Draw text: display.text(text, x, y, width, scale)
            # Width is the maximum width for text wrapping (use display width)
            self.display.text(text, x, y, self.display_width, scale)
        except Exception as e:
            print(f"Error drawing text: {e}")
            import sys
            try:
                sys.print_exception(e)
            except:
                pass
    
    def draw_flight_card(self, flight):
        """Draw a flight card on the display"""
        if not self.display:
            print(f"[SIM] Flight card: {flight.get('callsign', 'N/A')}")
            return
        
        width = self.display_width
        height = self.display_height
        
        # Clear display
        self.clear_display()
        
        # Header section with darker blue/purple background (reduced height)
        header_height = 55
        header_y = 0
        
        # Draw darker blue header background (more purple-blue like FlightAware)
        darker_blue = self.display.create_pen(20, 40, 120)  # Darker blue-purple
        self.draw_rectangle(0, header_y, width, header_height, darker_blue)
        
        # Callsign (large, white on blue) - left aligned, moved down 5px
        callsign = flight.get('callsign', 'N/A')
        self.draw_text(15, header_y + 23, callsign, size=42, color=(255, 255, 255), bold=True)
        
        # ICAO code (right below callsign, no gap) - left aligned
        icao = flight.get('icao', 'N/A')
        self.draw_text(15, header_y + 40, icao, size=26, color=(255, 255, 255))
        
        # Main content area (white background, starts after header - moved up)
        content_y = 60
        
        # Origin and Destination section - matching FlightAware style
        origin = flight.get('origin')
        origin_country = flight.get('origin_country', '')
        destination = flight.get('destination')
        destination_country = flight.get('destination_country', '')
        has_route = bool(origin and destination)
        
        if has_route:
            # Route display section
            route_section_y = content_y + 25
            
            # FROM label - left side
            self.draw_text(30, route_section_y, "FROM", size=18, color=(140, 140, 140))
            
            # Origin airport code - large, bold, blue (more spacing from label)
            # Positioned further left to make room for plane in center
            origin_y = route_section_y + 35
            self.draw_text(30, origin_y, origin, size=52, color=(59, 130, 246), bold=True)
            
            # Origin country - below airport code
            if origin_country:
                if len(origin_country) > 15:
                    origin_country = origin_country[:15]
                self.draw_text(30, route_section_y + 55, origin_country, size=18, color=(80, 80, 80))
            
            # Airplane icon in center, on the SAME LINE as airport codes
            # Text Y coordinate is the baseline, so align plane center to match text baseline
            plane_x = width // 2
            # For 52px text, baseline is at origin_y, text extends upward
            # Move plane up 10px to better align with visual center of airport codes
            plane_y = origin_y - 10
            
            # Draw single dash line on left side of plane (with more spacing)
            dash_x_left = plane_x - 35  # More space from plane
            self.draw_rectangle(dash_x_left, plane_y, 12, 2, self.accent_blue_pen)
            
            # Draw airplane icon
            self.draw_airplane_icon(plane_x, plane_y)
            
            # Draw single dash line on right side of plane (with more spacing)
            dash_x_right = plane_x + 23  # More space from plane
            self.draw_rectangle(dash_x_right, plane_y, 12, 2, self.accent_blue_pen)
            
            # TO label - right side
            to_label_x = width - 30
            self.draw_text(to_label_x, route_section_y, "TO", size=18, color=(140, 140, 140), right=True)
            
            # Destination airport code - large, bold, blue, right aligned (more spacing from label)
            # Positioned further right to make room for plane in center
            dest_x = width - 30
            self.draw_text(dest_x, origin_y, destination, size=52, color=(59, 130, 246), bold=True, right=True)
            
            # Destination country - below airport code, right aligned
            if destination_country:
                if len(destination_country) > 15:
                    destination_country = destination_country[:15]
                self.draw_text(dest_x, route_section_y + 55, destination_country, size=18, color=(80, 80, 80), right=True)
            
            # Flight metrics section - simplified to 3 columns like FlightAware
            # Moved up and closer spacing between labels and values
            stats_y = route_section_y + 90
            
            # Get values
            alt = flight.get('altitude', 0)
            speed = flight.get('speed', 0)
            distance = flight.get('distance', 0)
            
            # Column 1: ALTITUDE (reduced spacing between label and value)
            self.draw_text(40, stats_y, "ALTITUDE", size=18, color=(140, 140, 140))
            # Format altitude with comma
            alt_str = f"{int(alt):,} ft" if alt >= 1000 else f"{int(alt)} ft"
            self.draw_text(40, stats_y + 15, alt_str, size=18, color=(0, 0, 0))
            
            # Column 2: SPEED (centered, reduced spacing)
            speed_x = width // 2
            self.draw_text(speed_x, stats_y, "SPEED", size=18, color=(140, 140, 140), center=True)
            speed_str = f"{speed:.1f} kts"
            self.draw_text(speed_x, stats_y + 15, speed_str, size=18, color=(0, 0, 0), center=True)
            
            # Column 3: DISTANCE (right aligned, reduced spacing)
            dist_x = width - 40
            self.draw_text(dist_x, stats_y, "DISTANCE", size=18, color=(140, 140, 140), right=True)
            dist_str = f"{distance:.1f} nm"
            self.draw_text(dist_x, stats_y + 15, dist_str, size=18, color=(0, 0, 0), right=True)
        else:
            # No route - show dashes in FROM/TO section instead of position
            route_section_y = content_y + 25
            
            # FROM label - left side
            self.draw_text(30, route_section_y, "FROM", size=18, color=(140, 140, 140))
            
            # Origin airport code - show dashes
            origin_y = route_section_y + 35
            self.draw_text(30, origin_y, "---", size=52, color=(59, 130, 246), bold=True)
            
            # Airplane icon in center, on the SAME LINE as airport codes
            plane_x = width // 2
            plane_y = origin_y - 10
            
            # Draw single dash line on left side of plane
            dash_x_left = plane_x - 35
            self.draw_rectangle(dash_x_left, plane_y, 12, 2, self.accent_blue_pen)
            
            # Draw airplane icon
            self.draw_airplane_icon(plane_x, plane_y)
            
            # Draw single dash line on right side of plane
            dash_x_right = plane_x + 23
            self.draw_rectangle(dash_x_right, plane_y, 12, 2, self.accent_blue_pen)
            
            # TO label - right side
            to_label_x = width - 30
            self.draw_text(to_label_x, route_section_y, "TO", size=18, color=(140, 140, 140), right=True)
            
            # Destination airport code - show dashes
            dest_x = width - 30
            self.draw_text(dest_x, origin_y, "---", size=52, color=(59, 130, 246), bold=True, right=True)
            
            # Flight metrics section - simplified to 3 columns like FlightAware
            stats_y = route_section_y + 90
            
            # Get values
            alt = flight.get('altitude', 0)
            speed = flight.get('speed', 0)
            distance = flight.get('distance', 0)
            
            # Column 1: ALTITUDE
            self.draw_text(40, stats_y, "ALTITUDE", size=18, color=(140, 140, 140))
            alt_str = f"{int(alt):,} ft" if alt >= 1000 else f"{int(alt)} ft"
            self.draw_text(40, stats_y + 15, alt_str, size=18, color=(0, 0, 0))
            
            # Column 2: SPEED (centered)
            speed_x = width // 2
            self.draw_text(speed_x, stats_y, "SPEED", size=18, color=(140, 140, 140), center=True)
            speed_str = f"{speed:.1f} kts"
            self.draw_text(speed_x, stats_y + 15, speed_str, size=18, color=(0, 0, 0), center=True)
            
            # Column 3: DISTANCE (right aligned)
            dist_x = width - 40
            self.draw_text(dist_x, stats_y, "DISTANCE", size=18, color=(140, 140, 140), right=True)
            dist_str = f"{distance:.1f} nm"
            self.draw_text(dist_x, stats_y + 15, dist_str, size=18, color=(0, 0, 0), right=True)
        
        # Update display
        try:
            if self.presto:
                self.presto.update()
                # Ensure LEDs stay off if backlight is off (in case display update resets them)
                if not self.backlight_on:
                    # Try all methods to ensure LEDs stay off
                    if self.backlight_leds:
                        for i in range(7):
                            self.backlight_leds.set_rgb(i, 0, 0, 0)
                        if hasattr(self.backlight_leds, 'start'):
                            self.backlight_leds.start()
                        elif hasattr(self.backlight_leds, 'show'):
                            self.backlight_leds.show()
                    if hasattr(self.presto, 'set_led_rgb'):
                        for i in range(7):
                            self.presto.set_led_rgb(i, 0, 0, 0)
                    if hasattr(self.presto, 'backlight'):
                        try:
                            bl = self.presto.backlight
                            if hasattr(bl, 'set_rgb'):
                                for i in range(7):
                                    bl.set_rgb(i, 0, 0, 0)
                                if hasattr(bl, 'start'):
                                    bl.start()
                                elif hasattr(bl, 'show'):
                                    bl.show()
                        except:
                            pass
        except Exception as e:
            print(f"Error updating display: {e}")
    
    def draw_skies_clear_card(self, stats=None):
        """Draw a 'skies are clear' card when no flights are detected"""
        print(f"   Drawing skies clear card (display={self.display is not None}, presto={self.presto is not None})")
        
        if not self.display:
            print("[SIM] Skies are clear card")
            return
        
        width = self.display_width
        height = self.display_height
        
        print(f"   Display size: {width}x{height}")
        
        # Clear display
        self.clear_display()
        print("   Display cleared")
        
        # Draw blue header background
        header_height = 100
        self.draw_rectangle(0, 0, width, header_height, self.header_blue_pen)
        
        # Center content vertically
        center_y = height // 2
        
        # Main message - "SKIES ARE CLEAR" (white on blue header)
        self.draw_text(20, 30, "SKIES ARE", size=52, color=(255, 255, 255), bold=True)
        self.draw_text(20, 70, "CLEAR", size=72, color=(255, 255, 255), bold=True)
        
        # Status message (gray)
        self.draw_text(20, center_y + 70, "Monitoring...", size=24, color=(100, 100, 100))
        
        # Update display
        print("   Updating display...")
        try:
            if self.presto:
                self.presto.update()
                # Ensure LEDs stay off if backlight is off (in case display update resets them)
                if not self.backlight_on:
                    # Try all methods to ensure LEDs stay off
                    if self.backlight_leds:
                        for i in range(7):
                            self.backlight_leds.set_rgb(i, 0, 0, 0)
                        if hasattr(self.backlight_leds, 'start'):
                            self.backlight_leds.start()
                        elif hasattr(self.backlight_leds, 'show'):
                            self.backlight_leds.show()
                    if hasattr(self.presto, 'set_led_rgb'):
                        for i in range(7):
                            self.presto.set_led_rgb(i, 0, 0, 0)
                    if hasattr(self.presto, 'backlight'):
                        try:
                            bl = self.presto.backlight
                            if hasattr(bl, 'set_rgb'):
                                for i in range(7):
                                    bl.set_rgb(i, 0, 0, 0)
                                if hasattr(bl, 'start'):
                                    bl.start()
                                elif hasattr(bl, 'show'):
                                    bl.show()
                        except:
                            pass
                print("   ✓ Display updated")
            else:
                print("   ⚠️  Presto object is None")
        except Exception as e:
            print(f"   ✗ Error updating display: {e}")
            import sys
            try:
                sys.print_exception(e)
            except:
                pass
    
    def _parse_url(self, url):
        """Simple URL parser (MicroPython compatible)"""
        # Remove scheme if present
        if '://' in url:
            scheme, rest = url.split('://', 1)
        else:
            scheme = 'http'
            rest = url
        
        # Split host:port/path
        if '/' in rest:
            host_part, path = rest.split('/', 1)
            path = '/' + path
        else:
            host_part = rest
            path = '/events'
        
        # Split host and port
        if ':' in host_part:
            host, port_str = host_part.split(':', 1)
            port = int(port_str)
        else:
            host = host_part
            port = 443 if scheme == 'https' else 80
        
        return host, port, path
    
    def _poll_mode(self):
        """Polling mode using raw sockets (reliable in MicroPython)"""
        import socket
        
        print("Using polling mode with raw sockets (checking every 5 seconds)...")
        print("Double tap the display to toggle backlight on/off")
        print()
        
        # Parse URL manually (MicroPython doesn't have urllib.parse)
        host, port, path = self._parse_url(self.events_url)
        
        poll_count = 0
        while True:
            # Check for touch events (double tap to toggle backlight)
            self.check_touch_events()
            poll_count += 1
            try:
                print(f"\n🔄 Poll #{poll_count}: Fetching from {host}:{port}{path}")
                
                # Use raw socket (most reliable in MicroPython)
                # Note: MicroPython socket.settimeout() takes seconds as positional arg
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    sock.settimeout(10)  # 10 second timeout
                except TypeError:
                    # Some MicroPython versions don't support settimeout
                    pass
                
                try:
                    # Resolve hostname to IP address (MicroPython requires this)
                    print(f"   Resolving {host}...")
                    addr_info = socket.getaddrinfo(host, port)
                    if addr_info:
                        # getaddrinfo returns list of tuples: (family, type, proto, canonname, sockaddr)
                        # sockaddr is (ip, port) for AF_INET
                        addr = addr_info[0][4]  # Get (ip, port) tuple
                        print(f"   Resolved {host} to {addr[0]}:{addr[1]}")
                        sock.connect(addr)
                    else:
                        raise Exception("Could not resolve hostname")
                    
                    # Send HTTP GET request
                    request = f"GET {path} HTTP/1.1\r\n"
                    request += f"Host: {host}\r\n"
                    request += f"Accept: text/event-stream\r\n"
                    request += f"Connection: close\r\n"
                    request += f"\r\n"
                    
                    sock.send(request.encode())
                    
                    # Read response
                    response_data = b""
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        response_data += chunk
                        # Stop after we get enough data
                        if len(response_data) > 2000:
                            break
                    
                    sock.close()
                    
                    # Decode response (MicroPython decode doesn't accept keyword args)
                    try:
                        response_text = response_data.decode('utf-8')
                    except UnicodeDecodeError:
                        # Fallback: decode with error handling
                        response_text = response_data.decode('utf-8', 'ignore')
                    
                    # Skip HTTP headers (find body after \r\n\r\n)
                    body_start = response_text.find('\r\n\r\n')
                    if body_start != -1:
                        response_text = response_text[body_start + 4:]
                    
                    print(f"📥 Received {len(response_text)} bytes")
                    print(f"   First 200 chars: {response_text[:200]}")
                    
                    # Parse SSE format: "data: {...}\n\n"
                    lines = response_text.split('\n')
                    print(f"   Total lines: {len(lines)}")
                    
                    data_found = False
                    for line_num, line in enumerate(lines):
                        if line.startswith('data: '):
                            data_str = line[6:]  # Remove "data: " prefix
                            print(f"   Found data line {line_num}: {data_str[:100]}...")
                            try:
                                data = json.loads(data_str)
                                print(f"   ✓ JSON parsed successfully")
                                print(f"   Data type: {data.get('type')}")
                                
                                if data.get('type') == 'flight_update':
                                    flights = data.get('flights', [])
                                    stats = data.get('stats', {})
                                    
                                    print(f"   📊 Stats: {stats}")
                                    print(f"   ✈️  Flights count: {len(flights)}")
                                    
                                    if flights:
                                        # Prefer flights with routes, but show any flight if available
                                        best_flight = None
                                        flight_with_route = None
                                        
                                        for flight in flights:
                                            # First, try to find a flight with a complete route
                                            if flight.get('origin') and flight.get('destination'):
                                                flight_with_route = flight
                                                break
                                        
                                        # Use flight with route if found, otherwise use first flight
                                        best_flight = flight_with_route if flight_with_route else flights[0]
                                        
                                        if best_flight:
                                            # Log what we found
                                            has_route = bool(best_flight.get('origin') and best_flight.get('destination'))
                                            print(f"   Route info: {'✓ Has route' if has_route else '⚠️  No route (will show partial info)'}")
                                        
                                        if best_flight:
                                            self.current_flight = best_flight
                                            callsign = best_flight.get('callsign', 'N/A')
                                            origin = best_flight.get('origin', '---')
                                            destination = best_flight.get('destination', '---')
                                            print(f"   🎯 Selected flight: {callsign} ({origin} → {destination})")
                                            print(f"   Flight data keys: {list(best_flight.keys())}")
                                            print(f"   Drawing flight card...")
                                            self.draw_flight_card(best_flight)
                                            print(f"✓ Updated: {callsign} ({origin} → {destination})")
                                            data_found = True
                                        else:
                                            print("⚠️  No best flight selected after filtering")
                                    else:
                                        # No flights - show "skies are clear" card
                                        print("⏸️  No flights - showing skies are clear card")
                                        self.draw_skies_clear_card(stats)
                                    
                                    if data_found:
                                        break  # Found and processed data, stop parsing
                                else:
                                    print(f"   ⚠️  Unexpected data type: {data.get('type')}")
                            except json.JSONDecodeError as e:
                                print(f"⚠️  JSON parse error: {e}")
                                print(f"   Data: {data_str[:200]}")
                                continue
                    
                    if not data_found:
                        print("⚠️  No 'data:' lines found in response")
                        print(f"   Response preview: {response_text[:500]}")
                        
                except Exception as e:
                    sock.close()
                    print(f"⚠️  Socket error: {e}")
                    import sys
                    try:
                        sys.print_exception(e)
                    except:
                        pass
                    
            except Exception as e:
                print(f"⚠️  Polling error: {e}")
                import sys
                try:
                    sys.print_exception(e)
                except:
                    pass
            
            # Check touch more frequently during the wait period
            # Split the 5 second wait into smaller chunks to check touch
            for _ in range(50):  # 50 * 0.1s = 5 seconds
                self.check_touch_events()
                time.sleep(0.1)  # Check touch every 100ms
    
    def connect(self):
        """Connect to the flight tracker server and start displaying updates"""
        print(f"Connecting to flight tracker server: {self.events_url}")
        print("(Make sure WiFi is connected and server is reachable)")
        print("Press Ctrl+C to stop")
        
        # Use polling mode (socket-based, works in MicroPython)
        self._poll_mode()


def main():
    """Main entry point"""
    import sys
    
    # Simple argument parsing (MicroPython compatible)
    server_url = "http://piaware.local:5050"
    wifi_ssid = None
    wifi_password = None
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--server-url' and i + 1 < len(sys.argv):
            server_url = sys.argv[i + 1]
            i += 2
        elif arg == '--wifi-ssid' and i + 1 < len(sys.argv):
            wifi_ssid = sys.argv[i + 1]
            i += 2
        elif arg == '--wifi-password' and i + 1 < len(sys.argv):
            wifi_password = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    
    # Create client and connect
    client = PrestoFlightClient(server_url=server_url, wifi_ssid=wifi_ssid, wifi_password=wifi_password)
    
    try:
        client.connect()
    except KeyboardInterrupt:
        print("\n\nStopping client...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        import sys
        try:
            sys.print_exception(e)
        except:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
