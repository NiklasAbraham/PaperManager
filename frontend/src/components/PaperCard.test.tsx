import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import PaperCard from './PaperCard';
import * as client from '../api/client';
import type { Paper } from '../types';

vi.mock('../api/client', () => ({
  apiFetch: vi.fn(),
  deletePaper: vi.fn(),
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importActual) => {
  const actual = await importActual<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

const basePaper: Paper = {
  id: 'paper-1',
  title: 'Test Paper Title',
  created_at: '2024-01-01T00:00:00Z',
  reading_status: 'unread',
  rating: undefined,
  bookmarked: false,
};

function renderCard(paper: Paper = basePaper, onUpdated = vi.fn()) {
  return render(
    <MemoryRouter>
      <PaperCard paper={paper} onUpdated={onUpdated} />
    </MemoryRouter>
  );
}

describe('PaperCard — reading status', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.apiFetch).mockResolvedValue({ ...basePaper });
  });

  it('shows the unread status badge', () => {
    renderCard();
    expect(screen.getByTitle('Click to cycle reading status')).toBeInTheDocument();
    expect(screen.getByTitle('Click to cycle reading status')).toHaveTextContent('Unread');
  });

  it('cycles unread → reading on click', async () => {
    const user = userEvent.setup();
    const updated = { ...basePaper, reading_status: 'reading' as const };
    vi.mocked(client.apiFetch).mockResolvedValueOnce(updated);
    const onUpdated = vi.fn();

    renderCard(basePaper, onUpdated);
    await user.click(screen.getByTitle('Click to cycle reading status'));

    await waitFor(() => {
      expect(client.apiFetch).toHaveBeenCalledWith(
        `/papers/${basePaper.id}`,
        expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ reading_status: 'reading' }) })
      );
    });
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated));
  });

  it('cycles reading → read on click', async () => {
    const user = userEvent.setup();
    const readingPaper = { ...basePaper, reading_status: 'reading' as const };
    const updated = { ...basePaper, reading_status: 'read' as const };
    vi.mocked(client.apiFetch).mockResolvedValueOnce(updated);
    const onUpdated = vi.fn();

    renderCard(readingPaper, onUpdated);
    await user.click(screen.getByTitle('Click to cycle reading status'));

    await waitFor(() => {
      expect(client.apiFetch).toHaveBeenCalledWith(
        `/papers/${basePaper.id}`,
        expect.objectContaining({ body: JSON.stringify({ reading_status: 'read' }) })
      );
    });
  });

  it('cycles read → unread on click', async () => {
    const user = userEvent.setup();
    const readPaper = { ...basePaper, reading_status: 'read' as const };
    const updated = { ...basePaper, reading_status: 'unread' as const };
    vi.mocked(client.apiFetch).mockResolvedValueOnce(updated);

    renderCard(readPaper);
    await user.click(screen.getByTitle('Click to cycle reading status'));

    await waitFor(() => {
      expect(client.apiFetch).toHaveBeenCalledWith(
        `/papers/${basePaper.id}`,
        expect.objectContaining({ body: JSON.stringify({ reading_status: 'unread' }) })
      );
    });
  });

  it('does NOT navigate when status button is clicked', async () => {
    const user = userEvent.setup();
    vi.mocked(client.apiFetch).mockResolvedValueOnce({ ...basePaper, reading_status: 'reading' });

    renderCard();
    await user.click(screen.getByTitle('Click to cycle reading status'));

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('reverts optimistic update on API error', async () => {
    const user = userEvent.setup();
    vi.mocked(client.apiFetch).mockRejectedValueOnce(new Error('Network error'));

    renderCard();
    const badge = screen.getByTitle('Click to cycle reading status');
    expect(badge).toHaveTextContent('Unread');

    await user.click(badge);

    await waitFor(() => {
      expect(screen.getByTitle('Click to cycle reading status')).toHaveTextContent('Unread');
    });
  });
});

describe('PaperCard — bookmark', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the bookmark button', () => {
    renderCard();
    expect(screen.getByTitle('Bookmark this paper')).toBeInTheDocument();
  });

  it('toggles bookmark on and calls API', async () => {
    const user = userEvent.setup();
    const updated = { ...basePaper, bookmarked: true };
    vi.mocked(client.apiFetch).mockResolvedValueOnce(updated);
    const onUpdated = vi.fn();

    renderCard(basePaper, onUpdated);
    await user.click(screen.getByTitle('Bookmark this paper'));

    await waitFor(() => {
      expect(client.apiFetch).toHaveBeenCalledWith(
        `/papers/${basePaper.id}`,
        expect.objectContaining({ body: JSON.stringify({ bookmarked: true }) })
      );
    });
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated));
  });

  it('un-bookmarks when already bookmarked', async () => {
    const user = userEvent.setup();
    const bookmarkedPaper = { ...basePaper, bookmarked: true };
    const updated = { ...basePaper, bookmarked: false };
    vi.mocked(client.apiFetch).mockResolvedValueOnce(updated);

    renderCard(bookmarkedPaper);
    await user.click(screen.getByTitle('Remove bookmark'));

    await waitFor(() => {
      expect(client.apiFetch).toHaveBeenCalledWith(
        `/papers/${basePaper.id}`,
        expect.objectContaining({ body: JSON.stringify({ bookmarked: false }) })
      );
    });
  });

  it('does NOT navigate when bookmark button is clicked', async () => {
    const user = userEvent.setup();
    vi.mocked(client.apiFetch).mockResolvedValueOnce({ ...basePaper, bookmarked: true });

    renderCard();
    await user.click(screen.getByTitle('Bookmark this paper'));

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('reverts optimistic update on API error', async () => {
    const user = userEvent.setup();
    vi.mocked(client.apiFetch).mockRejectedValueOnce(new Error('Network error'));

    renderCard();
    await user.click(screen.getByTitle('Bookmark this paper'));

    await waitFor(() => {
      expect(screen.getByTitle('Bookmark this paper')).toBeInTheDocument();
    });
  });
});

describe('PaperCard — star rating', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders 5 star buttons', () => {
    renderCard();
    for (let i = 1; i <= 5; i++) {
      expect(screen.getByTitle(`Rate ${i} star${i > 1 ? 's' : ''}`)).toBeInTheDocument();
    }
  });

  it('sets rating to 3 stars when 3rd star is clicked', async () => {
    const user = userEvent.setup();
    const updated = { ...basePaper, rating: 3 };
    vi.mocked(client.apiFetch).mockResolvedValueOnce(updated);
    const onUpdated = vi.fn();

    renderCard(basePaper, onUpdated);
    await user.click(screen.getByTitle('Rate 3 stars'));

    await waitFor(() => {
      expect(client.apiFetch).toHaveBeenCalledWith(
        `/papers/${basePaper.id}`,
        expect.objectContaining({ body: JSON.stringify({ rating: 3 }) })
      );
    });
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(updated));
  });

  it('clears rating when same star is clicked again', async () => {
    const user = userEvent.setup();
    const ratedPaper = { ...basePaper, rating: 4 };
    const updated = { ...basePaper, rating: undefined };
    vi.mocked(client.apiFetch).mockResolvedValueOnce(updated);

    renderCard(ratedPaper);
    await user.click(screen.getByTitle('Rate 4 stars'));

    await waitFor(() => {
      expect(client.apiFetch).toHaveBeenCalledWith(
        `/papers/${basePaper.id}`,
        expect.objectContaining({ body: JSON.stringify({ rating: null }) })
      );
    });
  });

  it('does NOT navigate when a star is clicked', async () => {
    const user = userEvent.setup();
    vi.mocked(client.apiFetch).mockResolvedValueOnce({ ...basePaper, rating: 5 });

    renderCard();
    await user.click(screen.getByTitle('Rate 5 stars'));

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it('reverts optimistic rating on API error', async () => {
    const user = userEvent.setup();
    vi.mocked(client.apiFetch).mockRejectedValueOnce(new Error('Server error'));
    const ratedPaper = { ...basePaper, rating: 2 };

    renderCard(ratedPaper);
    await user.click(screen.getByTitle('Rate 5 stars'));

    await waitFor(() => {
      // After rollback, the 5-star button should not be filled
      const star5 = screen.getByTitle('Rate 5 stars');
      expect(star5).toHaveClass('text-gray-200');
    });
  });
});

describe('PaperCard — card click navigation', () => {
  it('navigates to paper detail when card body is clicked', async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByText('Test Paper Title'));
    expect(mockNavigate).toHaveBeenCalledWith(`/paper/${basePaper.id}`);
  });
});
