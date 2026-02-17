
def human_like_mobile_precise_tap(page, locator):
    """
    A precise mobile tap without micro-slides or excessive fuzziness.
    Useful for sensitive elements like dropdowns that might misinterpret
    sliding taps as drag/scroll events.
    """
    cdp = None
    try:
        locator.scroll_into_view_if_needed()
        locator.wait_for(state="visible", timeout=5000)
        box = locator.bounding_box()
        if not box: return False

        # Center target with very minimal variance (precision tap)
        target_x = box['x'] + (box['width'] / 2) + random.uniform(-2, 2)
        target_y = box['y'] + (box['height'] / 2) + random.uniform(-2, 2)
        
        # Clamp to box
        target_x = max(box['x'], min(target_x, box['x'] + box['width']))
        target_y = max(box['y'], min(target_y, box['y'] + box['height']))

        cdp = page.context.new_cdp_session(page)
        
        # Use simpler touch params for precise tap
        finger_props = {
            "radiusX": 8.0, 
            "radiusY": 8.0, 
            "force": 0.5, 
            "rotationAngle": 0.0,
            "id": _get_next_touch_id()
        }

        # 1. Touch Start
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": round(target_x, 2), "y": round(target_y, 2), **finger_props}]
        })

        # 2. Short Hold (Clean tap, no resize/slide)
        time.sleep(random.uniform(0.05, 0.10))

        # 3. Touch End
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        cdp.detach()
        cdp = None # Prevents finally block from trying to detach again if successful
        
        time.sleep(random.uniform(0.2, 0.4))
        return True

    except Exception as e:
        logger.error(f"Mobile Precise Tap Failed: {e}")
        return False
        
    finally:
        if cdp:
            try:
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                cdp.detach()
            except Exception: pass
