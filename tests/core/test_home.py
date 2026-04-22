from django.urls import reverse


def test_home_page_is_public(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert b"Get important messages without reading everything manually." in response.content
    assert b"Get started" in response.content
    assert b"How it works" in response.content


def test_home_page_shows_dashboard_cta_for_authenticated_user(client, user):
    client.force_login(user)

    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert b"Open dashboard" in response.content
    assert b"Get important messages without reading everything manually." in response.content


def test_about_page_is_public(client):
    response = client.get(reverse("about"))

    assert response.status_code == 200
    assert b"About InboxSignal" in response.content
    assert b"What the system does" in response.content
    assert b"Bot access only" in response.content
    assert b"Rules-first, AI-assisted" in response.content


def test_dashboard_stays_private_for_anonymous_user(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]