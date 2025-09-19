import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import NoteEditor from './NoteEditor';
import api from './api';
import axios from 'axios';

jest.mock('axios', () => {
  const mockAxios = {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
    create: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() }
    }
  };
  mockAxios.create.mockReturnValue(mockAxios);
  return mockAxios;
});

test('saves note via API', async () => {
  const token = 'test-token';
  localStorage.setItem('token', token);
  api.post.mockResolvedValue({
    data: {
      email: 's1@example.com',
      notes: [{ text: 'old' }, { text: 'hi' }],
    },
  });
  const onSaved = jest.fn();
  render(
    <NoteEditor jobCode="J1" email="s1@example.com" onSaved={onSaved} notes={[{ text: 'old' }]} />
  );
  expect(screen.getByRole('textbox').value).toBe('');
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hi' } });
  fireEvent.click(screen.getByText('Save'));
  await waitFor(() => {
    expect(api.post).toHaveBeenCalledWith(
      '/student-note',
      {
        job_code: 'J1',
        student_email: 's1@example.com',
        note: 'hi',
      },
      { headers: { Authorization: `Bearer ${token}` } }
    );
    expect(onSaved).toHaveBeenCalledWith({ text: 'hi' });
    expect(screen.getByRole('textbox').value).toBe('');
  });
  localStorage.clear();
});

test('starts with blank note even when history exists', () => {
  render(
    <NoteEditor jobCode="J1" email="s1@example.com" notes={[{ text: 'old note' }]} />
  );
  expect(screen.getByRole('textbox').value).toBe('');
});
