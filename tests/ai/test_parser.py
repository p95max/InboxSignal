from apps.ai.services.parser import parse_ai_analysis_response


def test_parse_ai_analysis_response_valid_json():
    result = parse_ai_analysis_response(
        """
        {
          "category": "complaint",
          "priority_score": 85,
          "summary": "Customer reports a damaged product.",
          "extracted": {
            "name": null,
            "contact": "buyer@example.com",
            "product_or_service": "product",
            "budget": null,
            "date_or_time": null
          }
        }
        """
    )

    assert result.category == "complaint"
    assert result.priority_score == 85
    assert result.summary == "Customer reports a damaged product."
    assert result.extracted_data["contact"] == "buyer@example.com"
    assert result.extracted_data["budget"] is None


def test_parse_ai_analysis_response_clamps_priority_score():
    result = parse_ai_analysis_response(
        """
        {
          "category": "lead",
          "priority_score": 150,
          "summary": "Customer asks about price.",
          "extracted": {}
        }
        """
    )

    assert result.category == "lead"
    assert result.priority_score == 100


def test_parse_ai_analysis_response_falls_back_to_info_for_unknown_category():
    result = parse_ai_analysis_response(
        """
        {
          "category": "unknown",
          "priority_score": 10,
          "summary": "Unknown message.",
          "extracted": {}
        }
        """
    )

    assert result.category == "info"