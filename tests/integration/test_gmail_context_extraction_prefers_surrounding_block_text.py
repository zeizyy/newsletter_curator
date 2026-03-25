from __future__ import annotations

from curator.content import extract_links_from_html


def test_gmail_context_extraction_prefers_surrounding_block_text():
    html = """
    <html>
      <body>
        <table>
          <tr>
            <td>
              <div>
                <strong>Nvidia's networking surge is becoming a second revenue engine.</strong>
                Jensen Huang says NVLink, InfiniBand, and optics are expanding the AI rack.
                <a href="https://example.com/nvidia-networking">Read More</a>
              </div>
            </td>
          </tr>
          <tr>
            <td>
              <p>
                Google is reshaping Workspace around Gemini-powered drafting and meeting workflows.
                <a href="https://example.com/google-workspace">Continue Reading</a>
              </p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    links = extract_links_from_html(html)

    assert len(links) == 2
    first = links[0]
    second = links[1]

    assert first["anchor_text"] == "Read More"
    assert "Read More" not in first["context"]
    assert "Nvidia's networking surge is becoming a second revenue engine." in first["context"]
    assert "NVLink, InfiniBand, and optics are expanding the AI rack." in first["context"]

    assert second["anchor_text"] == "Continue Reading"
    assert "Continue Reading" not in second["context"]
    assert "Google is reshaping Workspace around Gemini-powered drafting" in second["context"]

