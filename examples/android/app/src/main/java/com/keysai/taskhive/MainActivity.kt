package com.keysai.taskhive

import android.os.Bundle
import android.widget.ArrayAdapter
import androidx.appcompat.app.AppCompatActivity
import com.keysai.taskhive.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var db: TaskDb
    private val rows = mutableListOf<TaskDb.Task>()
    private lateinit var adapter: ArrayAdapter<String>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        db = TaskDb(this)
        adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, mutableListOf())
        binding.taskList.adapter = adapter

        binding.addButton.setOnClickListener {
            val title = binding.taskInput.text.toString()
            if (title.isBlank()) {
                binding.taskInput.error = getString(R.string.title_required)
            } else {
                db.add(title)
                binding.taskInput.text?.clear()
                refresh()
            }
        }

        binding.taskList.setOnItemClickListener { _, _, position, _ ->
            rows.getOrNull(position)?.let {
                db.toggle(it.id)
                refresh()
            }
        }

        refresh()
    }

    private fun refresh() {
        rows.clear()
        rows.addAll(db.all())
        adapter.clear()
        adapter.addAll(rows.map { (if (it.done) "✓  " else "•  ") + it.title })
        adapter.notifyDataSetChanged()
        binding.empty.text =
            if (rows.isEmpty()) getString(R.string.empty_state) else ""
    }
}
