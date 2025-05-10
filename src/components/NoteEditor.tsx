import { Box, TextField } from '@mui/material';
import type { Note } from '../types';
import { useEffect, useState } from 'react';

interface NoteEditorProps {
  note: Note | null;
  onUpdateNote: (note: Note) => void;
}

const NoteEditor = ({ note, onUpdateNote }: NoteEditorProps) => {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');

  useEffect(() => {
    if (note) {
      setTitle(note.title);
      setContent(note.content);
    } else {
      setTitle('');
      setContent('');
    }
  }, [note]);

  const handleTitleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newTitle = e.target.value;
    setTitle(newTitle);
    if (note) {
      onUpdateNote({ ...note, title: newTitle });
    }
  };

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newContent = e.target.value;
    setContent(newContent);
    if (note) {
      onUpdateNote({ ...note, content: newContent });
    }
  };

  if (!note) {
    return (
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.paper',
        }}
      >
        메모를 선택하거나 새 메모를 만들어주세요
      </Box>
    );
  }

  return (
    <Box
      sx={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'background.paper',
        p: 2,
      }}
    >
      <TextField
        fullWidth
        variant="standard"
        value={title}
        onChange={handleTitleChange}
        placeholder="제목"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        multiline
        value={content}
        onChange={handleContentChange}
        placeholder="내용을 입력하세요"
        sx={{ flex: 1 }}
        InputProps={{
          sx: {
            height: '100%',
            '& textarea': {
              height: '100% !important',
            },
          },
        }}
      />
    </Box>
  );
};

export default NoteEditor; 