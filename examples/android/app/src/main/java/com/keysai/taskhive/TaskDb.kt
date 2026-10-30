package com.keysai.taskhive

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/** One small table, no ORM — enough to show a real persistence layer. */
class TaskDb(context: Context) : SQLiteOpenHelper(context, NAME, null, VERSION) {

    data class Task(val id: Long, val title: String, val done: Boolean)

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE tasks (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                done  INTEGER NOT NULL DEFAULT 0
            )
            """.trimIndent()
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS tasks")
        onCreate(db)
    }

    fun all(): List<Task> {
        val out = mutableListOf<Task>()
        readableDatabase.rawQuery("SELECT id, title, done FROM tasks ORDER BY id DESC", null)
            .use { cursor ->
                while (cursor.moveToNext()) {
                    out += Task(cursor.getLong(0), cursor.getString(1), cursor.getInt(2) == 1)
                }
            }
        return out
    }

    fun add(title: String): Long {
        val values = ContentValues().apply {
            put("title", title.trim())
            put("done", 0)
        }
        return writableDatabase.insert("tasks", null, values)
    }

    fun toggle(id: Long) {
        writableDatabase.execSQL(
            "UPDATE tasks SET done = CASE WHEN done = 1 THEN 0 ELSE 1 END WHERE id = ?",
            arrayOf(id)
        )
    }

    companion object {
        private const val NAME = "taskhive.db"
        private const val VERSION = 1
    }
}
