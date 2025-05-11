import { useState, useEffect } from 'react'
import { Box, CssBaseline, ThemeProvider, createTheme, useMediaQuery, Button } from '@mui/material'
import Sidebar from './components/Sidebar'
import NoteList from './components/NoteList'
import NoteEditor from './components/NoteEditor'
import type { Note } from './types'
import { db } from './firebase'
import {
  collection,
  addDoc,
  updateDoc,
  deleteDoc,
  doc,
  onSnapshot,
  query,
  orderBy,
} from 'firebase/firestore'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#007AFF',
    },
  },
})

function App() {
  const [notes, setNotes] = useState<Note[]>([])
  const [selectedNote, setSelectedNote] = useState<Note | null>(null)
  const notesRef = collection(db, 'notes')
  const isMobile = useMediaQuery('(max-width:600px)')
  const [showDetail, setShowDetail] = useState(false)

  // Firestore에서 메모 실시간 구독
  useEffect(() => {
    const q = query(notesRef, orderBy('updatedAt', 'desc'))
    const unsubscribe = onSnapshot(q, (snapshot) => {
      const data = snapshot.docs.map((doc) => {
        const d = doc.data()
        return {
          id: doc.id,
          title: d.title,
          content: d.content,
          createdAt: d.createdAt?.toDate ? d.createdAt.toDate() : new Date(),
          updatedAt: d.updatedAt?.toDate ? d.updatedAt.toDate() : new Date(),
        } as Note
      })
      setNotes(data)
      // 선택된 메모가 삭제된 경우 자동 해제
      if (selectedNote && !data.find(n => n.id === selectedNote.id)) {
        setSelectedNote(null)
      }
    })
    return () => unsubscribe()
  }, [selectedNote])

  // Firestore에 새 메모 추가
  const handleCreateNote = async () => {
    const now = new Date()
    const newNote = {
      title: '새 메모',
      content: '',
      createdAt: now,
      updatedAt: now,
    }
    const docRef = await addDoc(notesRef, newNote)
    setSelectedNote({ ...newNote, id: docRef.id })
  }

  // Firestore에서 메모 수정
  const handleUpdateNote = async (updatedNote: Note) => {
    const ref = doc(db, 'notes', updatedNote.id)
    await updateDoc(ref, {
      title: updatedNote.title,
      content: updatedNote.content,
      updatedAt: new Date(),
    })
    setSelectedNote({ ...updatedNote, updatedAt: new Date() })
  }

  // Firestore에서 메모 삭제
  const handleDeleteNote = async (noteId: string) => {
    await deleteDoc(doc(db, 'notes', noteId))
    if (selectedNote?.id === noteId) {
      setSelectedNote(null)
    }
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ height: '100vh', width: '100vw', overflow: 'hidden' }}>
        {isMobile ? (
          showDetail && selectedNote ? (
            <Box sx={{ height: '100%', width: '100%', display: 'flex', flexDirection: 'column' }}>
              <Box sx={{ p: 1 }}>
                <Button variant="text" onClick={() => setShowDetail(false)} sx={{ fontSize: 18 }}>← 뒤로</Button>
              </Box>
              <NoteEditor
                note={selectedNote}
                onUpdateNote={handleUpdateNote}
              />
            </Box>
          ) : (
            <NoteList
              notes={notes}
              selectedNote={selectedNote}
              onSelectNote={note => {
                setSelectedNote(note);
                setShowDetail(true);
              }}
              onDeleteNote={handleDeleteNote}
            />
          )
        ) : (
          <Box sx={{ display: 'flex', height: '100vh' }}>
            <Sidebar onCreateNote={handleCreateNote} />
            <Box sx={{ display: 'flex', flex: 1 }}>
              <NoteList
                notes={notes}
                selectedNote={selectedNote}
                onSelectNote={setSelectedNote}
                onDeleteNote={handleDeleteNote}
              />
              <NoteEditor
                note={selectedNote}
                onUpdateNote={handleUpdateNote}
              />
            </Box>
          </Box>
        )}
      </Box>
    </ThemeProvider>
  )
}

export default App
