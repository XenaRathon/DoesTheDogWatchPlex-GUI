import pytest
from unittest.mock import Mock, call
from plex_warnings import clear_warnings

def test_clear_warnings_none_index():
    mock_plex = Mock()
    mock_library = Mock()
    mock_library.type = "show"
    mock_library.title = "TV Shows"

    mock_show = Mock()
    mock_show.title = "A Show"
    mock_show.summary = "A Show summary\ndoesthedogdie: foo"

    mock_season = Mock()
    mock_season.index = None
    mock_season.summary = "Season summary"

    mock_season_2 = Mock()
    mock_season_2.index = 1
    mock_season_2.summary = "Season 1 summary"

    mock_episode = Mock()
    mock_episode.index = None
    mock_episode.summary = "Episode summary"

    mock_episode_2 = Mock()
    mock_episode_2.index = 1
    mock_episode_2.summary = "Episode 1 summary"

    mock_season.episodes.return_value = [mock_episode]
    mock_season_2.episodes.return_value = [mock_episode_2]
    mock_show.seasons.return_value = [mock_season, mock_season_2]
    mock_library.all.return_value = [mock_show]
    mock_plex.library.sections.return_value = [mock_library]

    # Run the function. It should not crash.
    clear_warnings(mock_plex, None, ["tv_shows"])

    # Assert that editSummary was called on the show.
    mock_show.editSummary.assert_called_once()

    # Assert that editSummary was called on season 2 and episode 2, but not season 1 or episode 1.
    mock_season.editSummary.assert_not_called()
    mock_episode.editSummary.assert_not_called()
    mock_season_2.editSummary.assert_not_called() # Actually, there were no warnings on season 2 / episode 2 to clear in our mock. Wait, strip_warnings checks if original summary has separator.

    # Let's add a warning to season 2 so we can assert it was cleared.
    mock_season_2.summary = "Season 2 summary\ndoesthedogdie: warning"
    mock_episode_2.summary = "Episode 2 summary\ndoesthedogdie: warning"

    # Reset mocks
    mock_show.editSummary.reset_mock()
    mock_season_2.editSummary.reset_mock()
    mock_episode_2.editSummary.reset_mock()

    clear_warnings(mock_plex, None, ["tv_shows"])

    # Should be called
    mock_show.editSummary.assert_called_once()
    mock_season_2.editSummary.assert_called_once_with("Season 2 summary")
    mock_episode_2.editSummary.assert_called_once_with("Episode 2 summary")

    mock_season.editSummary.assert_not_called()
    mock_episode.editSummary.assert_not_called()
